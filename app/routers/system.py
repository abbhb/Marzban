from typing import Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app import __version__, xray
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.proxy import ProxyHost, ProxyInbound, ProxyTypes
from app.models.system import SystemStats
from app.models.user import UserStatus
from app.utils import responses
from app.utils.system import cpu_usage, memory_usage, realtime_bandwidth
from app.services import cascades
from app.services.external_subscriptions import ExternalSubscriptionError

router = APIRouter(tags=["System"], prefix="/api", responses={401: responses._401})


@router.get("/hosts/cascade-entries")
def get_cascade_entries(search: str = Query("", max_length=256), selected_id: int | None = Query(None, gt=0),
                        db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)):
    return cascades.entry_choices(db, search.strip(), selected_id)


class CascadePreview(BaseModel):
    yaml_text: str = Field(alias="yaml", max_length=32768, repr=False)


@router.post("/hosts/cascade-preview")
def preview_cascade_entry(body: CascadePreview, admin: Admin = Depends(Admin.check_sudo_admin)):
    try:
        node = cascades.parse_entry_yaml(body.yaml_text)
    except cascades.CascadeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {key: node[key] for key in ("name", "type", "server", "port")}


@router.get("/system", response_model=SystemStats)
def get_system_stats(
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.get_current)
):
    """Fetch system stats including memory, CPU, and user metrics."""
    mem = memory_usage()
    cpu = cpu_usage()
    system = crud.get_system_usage(db)
    dbadmin: Union[Admin, None] = crud.get_admin(db, admin.username)

    total_user = crud.get_users_count(db, admin=dbadmin if not admin.is_sudo else None)
    users_active = crud.get_users_count(
        db, status=UserStatus.active, admin=dbadmin if not admin.is_sudo else None
    )
    users_disabled = crud.get_users_count(
        db, status=UserStatus.disabled, admin=dbadmin if not admin.is_sudo else None
    )
    users_on_hold = crud.get_users_count(
        db, status=UserStatus.on_hold, admin=dbadmin if not admin.is_sudo else None
    )
    users_expired = crud.get_users_count(
        db, status=UserStatus.expired, admin=dbadmin if not admin.is_sudo else None
    )
    users_limited = crud.get_users_count(
        db, status=UserStatus.limited, admin=dbadmin if not admin.is_sudo else None
    )
    online_users = crud.count_online_users(db, 24)
    realtime_bandwidth_stats = realtime_bandwidth()

    return SystemStats(
        version=__version__,
        mem_total=mem.total,
        mem_used=mem.used,
        cpu_cores=cpu.cores,
        cpu_usage=cpu.percent,
        total_user=total_user,
        online_users=online_users,
        users_active=users_active,
        users_disabled=users_disabled,
        users_expired=users_expired,
        users_limited=users_limited,
        users_on_hold=users_on_hold,
        incoming_bandwidth=system.uplink,
        outgoing_bandwidth=system.downlink,
        incoming_bandwidth_speed=realtime_bandwidth_stats.incoming_bytes,
        outgoing_bandwidth_speed=realtime_bandwidth_stats.outgoing_bytes,
    )


@router.get("/inbounds", response_model=Dict[ProxyTypes, List[ProxyInbound]])
def get_inbounds(admin: Admin = Depends(Admin.get_current)):
    """Retrieve inbound configurations grouped by protocol."""
    return xray.config.inbounds_by_protocol


@router.get(
    "/hosts", response_model=Dict[str, List[ProxyHost]], responses={403: responses._403}
)
def get_hosts(
    db: Session = Depends(get_db), admin: Admin = Depends(Admin.check_sudo_admin)
):
    """Get a list of proxy hosts grouped by inbound tag."""
    hosts = {tag: crud.get_hosts(db, tag) for tag in xray.config.inbounds_by_tag}
    return hosts


@router.put(
    "/hosts", response_model=Dict[str, List[ProxyHost]], responses={403: responses._403}
)
def modify_hosts(
    modified_hosts: Dict[str, List[ProxyHost]],
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    """Modify proxy hosts and update the configuration."""
    for inbound_tag in modified_hosts:
        if inbound_tag not in xray.config.inbounds_by_tag:
            raise HTTPException(
                status_code=400, detail=f"Inbound {inbound_tag} doesn't exist"
            )

    try:
        cascades.validate_hosts(db, modified_hosts)
        for inbound_tag, hosts in modified_hosts.items():
            crud.update_hosts(db, inbound_tag, hosts, commit=False)
        db.commit()
    except (cascades.CascadeError, ExternalSubscriptionError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="cascade_entry_unavailable") from None

    xray.hosts.update()

    return {tag: crud.get_hosts(db, tag) for tag in xray.config.inbounds_by_tag}
