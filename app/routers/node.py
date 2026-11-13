import asyncio
import time
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket
from sqlalchemy.exc import IntegrityError
from starlette.websockets import WebSocketDisconnect

from app import logger, xray
from app.db import Session, crud, get_db
from app.dependencies import get_dbnode, validate_dates
from app.models.admin import Admin
from app.models.node import (
    NodeCreate,
    NodeModify,
    NodeResponse,
    NodeServiceResponse,
    NodeSettings,
    NodeStatus,
    NodesUsageResponse,
)
from app.models.proxy import ProxyHost
from app.services.node_connections import ConnectionObservations
from app.utils import responses

router = APIRouter(
    tags=["Node"], prefix="/api", responses={401: responses._401, 403: responses._403}
)


@router.get("/node-services", response_model=List[NodeServiceResponse])
def get_node_services(
    db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)
):
    """Service hosts, including the panel's own Xray (reserved ID 0)."""
    nodes = [NodeResponse(
        id=0, name="Panel core", address="localhost", port=0, api_port=0,
        xray_version=xray.core.version,
        status=NodeStatus.connected if xray.core.started else NodeStatus.disabled,
    ), *crud.get_nodes(db)]
    return [NodeServiceResponse(
        **NodeResponse.model_validate(node).model_dump(),
        inbound_tags=[tag for tag in xray.config.inbounds_by_tag
                      if xray.config.has_inbound_on(tag, node.id or None)],
    ) for node in nodes]


@router.websocket("/node/{node_id}/connections")
async def node_connections(node_id: int, websocket: WebSocket, db: Session = Depends(get_db)):
    """Observe one host without reconnecting, restarting or changing its core.

    Credentials arrive in the first frame, keeping them out of URLs and logs.
    Buffers and the remote log subscription are released when the tab closes.
    """
    await websocket.accept()
    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        token = auth.get("token") if isinstance(auth, dict) else None
        admin = Admin.get_admin(token, db) if isinstance(token, str) else None
        if not admin:
            return await websocket.close(code=4401, reason="Unauthorized")
        if not admin.is_sudo:
            return await websocket.close(code=4403, reason="Forbidden")
        if node_id == 0:
            source = xray.core
            available = source.started
        else:
            dbnode = crud.get_node_by_id(db, node_id)
            if not dbnode:
                return await websocket.close(code=4404, reason="Node not found")
            source = xray.nodes.get(node_id)
            available = source is not None and dbnode.status == NodeStatus.connected
        if not available:
            return await websocket.close(code=4400, reason="Node is not connected")
        db.close()

        observations = ConnectionObservations()
        last_sent = 0.0
        dirty = True
        with source.get_logs() as logs:
            while True:
                current = xray.core if node_id == 0 else xray.nodes.get(node_id)
                if current is not source or (node_id == 0 and not source.started):
                    return await websocket.close(code=4410, reason="Core changed; reopen observations")
                # A busy host must still yield to disconnects and other clients.
                for _ in range(min(len(logs), 200)):
                    dirty = observations.feed(logs.popleft()) or dirty
                now = time.monotonic()
                if (dirty and now - last_sent >= 0.75) or now - last_sent >= 15:
                    await websocket.send_json(observations.snapshot())
                    last_sent, dirty = now, False
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    if message["type"] == "websocket.disconnect":
                        break
                except asyncio.TimeoutError:
                    pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    except (ValueError, asyncio.TimeoutError):
        await websocket.close(code=4401, reason="Authentication required")
    except (ConnectionError, OSError):
        await websocket.close(code=4420, reason="Observation stream unavailable")


def add_host_if_needed(new_node: NodeCreate, db: Session):
    """Add a host if specified in the new node settings."""
    if new_node.add_as_new_host:
        host = ProxyHost(
            remark=f"{new_node.name} ({{USERNAME}}) [{{PROTOCOL}} - {{TRANSPORT}}]",
            address=new_node.address,
        )
        for inbound_tag in xray.config.inbounds_by_tag:
            crud.add_host(db, inbound_tag, host)
        xray.hosts.update()


@router.get("/node/settings", response_model=NodeSettings)
def get_node_settings(
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Retrieve the current node settings, including TLS certificate."""
    tls = crud.get_tls_certificate(db)
    return NodeSettings(certificate=tls.certificate)


@router.post("/node", response_model=NodeResponse, responses={409: responses._409})
def add_node(
    new_node: NodeCreate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Add a new node to the database and optionally add it as a host."""
    try:
        dbnode = crud.create_node(db, new_node)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f'Node "{new_node.name}" already exists'
        )

    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    bg.add_task(add_host_if_needed, new_node, db)

    logger.info(f'New node "{dbnode.name}" added')
    return dbnode


@router.get("/node/{node_id}", response_model=NodeResponse)
def get_node(
    dbnode: NodeResponse = Depends(get_dbnode),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Retrieve details of a specific node by its ID."""
    return dbnode


@router.websocket("/node/{node_id}/logs")
async def node_logs(node_id: int, websocket: WebSocket, db: Session = Depends(get_db)):
    token = websocket.query_params.get("token") or websocket.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")
    admin = Admin.get_admin(token, db)
    if not admin:
        return await websocket.close(reason="Unauthorized", code=4401)

    if not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    if not xray.nodes.get(node_id):
        return await websocket.close(reason="Node not found", code=4404)

    if not xray.nodes[node_id].connected:
        return await websocket.close(reason="Node is not connected", code=4400)

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
    node = xray.nodes[node_id]
    with node.get_logs() as logs:
        while True:
            if not node == xray.nodes[node_id]:
                break

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


@router.get("/nodes", response_model=List[NodeResponse])
def get_nodes(
    db: Session = Depends(get_db), _: Admin = Depends(Admin.check_sudo_admin)
):
    """Retrieve a list of all nodes. Accessible only to sudo admins."""
    return crud.get_nodes(db)


@router.put("/node/{node_id}", response_model=NodeResponse)
def modify_node(
    modified_node: NodeModify,
    bg: BackgroundTasks,
    dbnode: NodeResponse = Depends(get_node),
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Update a node's details. Only accessible to sudo admins."""
    updated_node = crud.update_node(db, dbnode, modified_node)
    xray.operations.remove_node(updated_node.id)
    if updated_node.status != NodeStatus.disabled:
        bg.add_task(xray.operations.connect_node, node_id=updated_node.id)

    logger.info(f'Node "{dbnode.name}" modified')
    return dbnode


@router.post("/node/{node_id}/reconnect")
def reconnect_node(
    bg: BackgroundTasks,
    dbnode: NodeResponse = Depends(get_node),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Trigger a reconnection for the specified node. Only accessible to sudo admins."""
    bg.add_task(xray.operations.connect_node, node_id=dbnode.id)
    return {"detail": "Reconnection task scheduled"}


@router.delete("/node/{node_id}")
def remove_node(
    dbnode: NodeResponse = Depends(get_node),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Delete a node and remove it from xray in the background."""
    crud.remove_node(db, dbnode)
    xray.operations.remove_node(dbnode.id)

    logger.info(f'Node "{dbnode.name}" deleted')
    return {}


@router.get("/nodes/usage", response_model=NodesUsageResponse)
def get_usage(
    db: Session = Depends(get_db),
    start: str = "",
    end: str = "",
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Retrieve usage statistics for nodes within a specified date range."""
    start, end = validate_dates(start, end)

    usages = crud.get_nodes_usage(db, start, end)

    return {"usages": usages}
