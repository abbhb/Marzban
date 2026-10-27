import asyncio
import json
import time
import hashlib
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import commentjson
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from app import xray
from app.db import Session, get_db
from app.models.admin import Admin
from app.models.core import CoreStats
from app.utils import responses
from app.xray import XRayConfig
from config import XRAY_JSON
from app.xray.flow import FLOW_KEY, supports_vision
from app.services.xhttp_profiles import PROFILE_KEY, profile_document, validate_profiles

router = APIRouter(tags=["Core"], prefix="/api", responses={401: responses._401})
# main.py deliberately runs one worker: serialize its core-file writers.
_core_config_lock = RLock()


def _flow_document():
    with open(XRAY_JSON) as stream:
        return commentjson.loads(stream.read())


def _flow_revision(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()


def _write_core_document(document):
    """An interrupted write must not truncate the live configuration."""
    target = Path(XRAY_JSON)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), target.stat().st_mode & 0o777)
            json.dump(document, stream, indent=4)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class XhttpProfilesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=64)
    inbounds: dict[str, list[dict]] = Field(max_length=256)


@router.get("/core/xhttp-profiles")
def get_xhttp_profiles(admin: Admin = Depends(Admin.check_sudo_admin)):
    with _core_config_lock:
        document = _flow_document()
        try:
            return profile_document(XRayConfig(document, api_port=xray.config.api_port), xray.hosts, _flow_revision(document))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None


@router.put("/core/xhttp-profiles")
def put_xhttp_profiles(values: XhttpProfilesUpdate, admin: Admin = Depends(Admin.check_sudo_admin)):
    with _core_config_lock:
        document = _flow_document()
        if _flow_revision(document) != values.revision:
            raise HTTPException(409, "Core configuration changed; reload before saving")
        if len(json.dumps(values.inbounds)) > 262144:
            raise HTTPException(400, "XHTTP profiles are too large")
        current = XRayConfig(document, api_port=xray.config.api_port)
        raw = {item["tag"]: item for item in document["inbounds"]}
        for tag, profiles in values.inbounds.items():
            inbound = current.inbounds_by_tag.get(tag)
            if not inbound or inbound["network"] not in ("xhttp", "splithttp"):
                raise HTTPException(400, "Unknown XHTTP inbound")
            try:
                raw[tag][PROFILE_KEY] = validate_profiles(profiles, inbound.get("path", ""))
            except ValueError as error:
                raise HTTPException(400, f"{tag}: {error}") from None
        candidate = XRayConfig(document, api_port=xray.config.api_port)
        # Build the response before committing so validation failures cannot
        # leave a partially saved document. No listener or account data changes.
        response = profile_document(candidate, xray.hosts, _flow_revision(document))
        try:
            _write_core_document(document)
        except OSError:
            raise HTTPException(503, "Could not save XHTTP profiles; retry later") from None
        xray.config = candidate
        return response


class InboundFlowsUpdate(BaseModel):
    revision: str
    flows: dict[str, Literal["", "xtls-rprx-vision"]]


@router.get("/core/inbound-flows")
def get_inbound_flows(admin: Admin = Depends(Admin.check_sudo_admin)):
    document = _flow_document()
    return {"revision": _flow_revision(document), "inbounds": [
        {"tag": tag, "flow": inbound.get("flow_override") or "", "supported": supports_vision(inbound)}
        for tag, inbound in xray.config.inbounds_by_tag.items()
        if inbound["protocol"] == "vless"
    ]}


@router.put("/core/inbound-flows")
def put_inbound_flows(values: InboundFlowsUpdate, admin: Admin = Depends(Admin.check_sudo_admin)):
    with _core_config_lock:
        document = _flow_document()
        if _flow_revision(document) != values.revision:
            raise HTTPException(409, "Core configuration changed; reload before saving")
        if len(values.flows) > 256:
            raise HTTPException(400, "Too many inbounds")
        raw = {i["tag"]: i for i in document["inbounds"]}
        for tag, flow in values.flows.items():
            inbound = xray.config.inbounds_by_tag.get(tag)
            if not inbound or inbound["protocol"] != "vless" or tag not in raw:
                raise HTTPException(400, "Unknown VLESS inbound")
            if flow and not supports_vision(inbound):
                raise HTTPException(400, "Vision requires a supported TLS/Reality transport")
            raw[tag][FLOW_KEY] = flow
        modify_core_config(document, admin)
        return get_inbound_flows(admin)


@router.websocket("/core/logs")
async def core_logs(websocket: WebSocket, db: Session = Depends(get_db)):
    token = websocket.query_params.get("token") or websocket.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")
    admin = Admin.get_admin(token, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    if not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    interval = websocket.query_params.get("interval")
    if interval:
        try:
            interval = float(interval)
        except ValueError:
            return await websocket.close(reason="Invalid interval value", code=4400)
        if interval > 10:
            return await websocket.close(
                reason="Interval must be more than 0 and at most 10 seconds", code=4400
            )

    await websocket.accept()

    cache = ""
    last_sent_ts = 0
    with xray.core.get_logs() as logs:
        while True:
            if interval and time.time() - last_sent_ts >= interval and cache:
                try:
                    await websocket.send_text(cache)
                except (WebSocketDisconnect, RuntimeError):
                    break
                cache = ""
                last_sent_ts = time.time()

            if not logs:
                try:
                    await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    continue
                except asyncio.TimeoutError:
                    continue
                except (WebSocketDisconnect, RuntimeError):
                    break

            log = logs.popleft()

            if interval:
                cache += f"{log}\n"
                continue

            try:
                await websocket.send_text(log)
            except (WebSocketDisconnect, RuntimeError):
                break


@router.get("/core", response_model=CoreStats)
def get_core_stats(admin: Admin = Depends(Admin.get_current)):
    """Retrieve core statistics such as version and uptime."""
    return CoreStats(
        version=xray.core.version,
        started=xray.core.started,
        logs_websocket=router.url_path_for("core_logs"),
    )


@router.post("/core/restart", responses={403: responses._403})
def restart_core(admin: Admin = Depends(Admin.check_sudo_admin)):
    """Restart the core and all connected nodes."""
    startup_config = xray.config.include_db_users()
    xray.core.restart(startup_config)

    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            xray.operations.restart_node(node_id, startup_config)

    return {}


@router.get("/core/config", responses={403: responses._403})
def get_core_config(admin: Admin = Depends(Admin.check_sudo_admin)) -> dict:
    """Get the current core configuration."""
    with open(XRAY_JSON, "r") as f:
        config = commentjson.loads(f.read())

    return config


@router.put("/core/config", responses={403: responses._403})
def modify_core_config(
    payload: dict, admin: Admin = Depends(Admin.check_sudo_admin)
) -> dict:
    """Modify the core configuration and restart the core."""
    with _core_config_lock:
        try:
            config = XRayConfig(payload, api_port=xray.config.api_port)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

        _write_core_document(payload)
        xray.config = config
        startup_config = xray.config.include_db_users()
        xray.core.restart(startup_config)
        for node_id, node in list(xray.nodes.items()):
            if node.connected:
                xray.operations.restart_node(node_id, startup_config)

        xray.hosts.update()
        return payload
