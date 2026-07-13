import time
import traceback
from dataclasses import dataclass
from typing import Optional

from app import app, logger, scheduler, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.xray.node import NodeAPIError, NodeSessionError
from config import (
    JOB_CORE_HEALTH_CHECK_FAILURE_THRESHOLD,
    JOB_CORE_HEALTH_CHECK_INTERVAL,
    JOB_CORE_HEALTH_CHECK_TIMEOUT,
)
from xray_api import exc as xray_exc


CONTROL_UNAVAILABLE = "control_unavailable"
SESSION_INVALID = "session_invalid"
CORE_STOPPED = "core_stopped"
STATS_UNAVAILABLE = "stats_unavailable"


@dataclass(frozen=True)
class NodeHealthFailure:
    kind: str
    reason: str


_node_health_failures = {}


def _error_detail(exc: Exception) -> str:
    detail = getattr(exc, "detail", None) or getattr(exc, "details", None) or str(exc)
    return " ".join(str(detail or exc.__class__.__name__).split())[:500]


def _node_api_failure(exc: NodeAPIError) -> NodeHealthFailure:
    if isinstance(exc, NodeSessionError) or exc.status_code in (401, 403):
        return NodeHealthFailure(SESSION_INVALID, _error_detail(exc))
    return NodeHealthFailure(CONTROL_UNAVAILABLE, _error_detail(exc))


def _probe_node(node) -> Optional[NodeHealthFailure]:
    try:
        connected = node.check_connection(timeout=JOB_CORE_HEALTH_CHECK_TIMEOUT)
    except NodeAPIError as exc:
        return _node_api_failure(exc)

    if not connected:
        return NodeHealthFailure(SESSION_INVALID, "node control session is not connected")

    try:
        started = node.check_started(timeout=JOB_CORE_HEALTH_CHECK_TIMEOUT)
    except NodeAPIError as exc:
        return _node_api_failure(exc)

    if not started:
        return NodeHealthFailure(CORE_STOPPED, "remote Xray process reports started=false")

    try:
        node.api.get_sys_stats(timeout=JOB_CORE_HEALTH_CHECK_TIMEOUT)
    except (ConnectionError, xray_exc.XrayError) as exc:
        return NodeHealthFailure(STATS_UNAVAILABLE, _error_detail(exc))

    return None


def _record_failure(node_id: int, failure: NodeHealthFailure) -> int:
    previous = _node_health_failures.get(node_id)
    count = previous["count"] + 1 if previous and previous["kind"] == failure.kind else 1
    _node_health_failures[node_id] = {
        "count": count,
        "kind": failure.kind,
        "reason": failure.reason,
    }
    return count


def _record_recovery(node_id: int, node) -> None:
    previous = _node_health_failures.pop(node_id, None)
    if previous:
        logger.info(
            "Node health check recovered: node_id=%s address=%s previous_failure=%s "
            "consecutive_failures=%s",
            node_id,
            getattr(node, "address", "unknown"),
            previous["kind"],
            previous["count"],
        )


def core_health_check():
    config = None
    failure_threshold = max(1, JOB_CORE_HEALTH_CHECK_FAILURE_THRESHOLD)

    # main core
    if not xray.core.started:
        logger.warning("Restarting main Xray core; reason=local core process is not running")
        if not config:
            config = xray.config.include_db_users()
        xray.core.restart(config)

    # nodes' core
    active_node_ids = set(xray.nodes)
    for stale_node_id in set(_node_health_failures) - active_node_ids:
        _node_health_failures.pop(stale_node_id, None)

    for node_id, node in list(xray.nodes.items()):
        failure = _probe_node(node)
        if failure is None:
            _record_recovery(node_id, node)
            continue

        consecutive_failures = _record_failure(node_id, failure)
        logger.warning(
            "Node health check failed: node_id=%s address=%s failure=%s reason=%s "
            "consecutive_failures=%s threshold=%s action=%s",
            node_id,
            getattr(node, "address", "unknown"),
            failure.kind,
            failure.reason,
            consecutive_failures,
            failure_threshold,
            "defer" if consecutive_failures < failure_threshold else "evaluate",
        )

        if consecutive_failures < failure_threshold:
            continue

        action_reason = (
            f"health check failure={failure.kind}; reason={failure.reason}; "
            f"consecutive_failures={consecutive_failures}; "
            f"interval={JOB_CORE_HEALTH_CHECK_INTERVAL}s; timeout={JOB_CORE_HEALTH_CHECK_TIMEOUT}s"
        )

        if failure.kind == CONTROL_UNAVAILABLE:
            if consecutive_failures == failure_threshold:
                logger.error(
                    "Node control plane is unavailable after %s consecutive checks; preserving the "
                    "remote Xray data plane and skipping automatic restart/reconnect: node_id=%s "
                    "address=%s reason=%s",
                    consecutive_failures,
                    node_id,
                    getattr(node, "address", "unknown"),
                    failure.reason,
                )
            continue

        _node_health_failures.pop(node_id, None)
        if not config:
            config = xray.config.include_db_users()

        if failure.kind == SESSION_INVALID:
            logger.error(
                "Scheduling node reconnect after confirmed control-session failure: node_id=%s "
                "address=%s reason=%s",
                node_id,
                getattr(node, "address", "unknown"),
                action_reason,
            )
            xray.operations.connect_node(node_id, config, reason=action_reason)
            continue

        logger.error(
            "Scheduling remote Xray restart after confirmed health failure: node_id=%s address=%s "
            "reason=%s",
            node_id,
            getattr(node, "address", "unknown"),
            action_reason,
        )
        xray.operations.restart_node(node_id, config, reason=action_reason)


@app.on_event("startup")
def start_core():
    _node_health_failures.clear()
    logger.info("Generating Xray core config")

    start_time = time.time()
    config = xray.config.include_db_users()
    logger.info(f"Xray core config generated in {(time.time() - start_time):.2f} seconds")

    # main core
    logger.info("Starting main Xray core")
    try:
        xray.core.start(config)
    except Exception:
        traceback.print_exc()

    # nodes' core
    logger.info("Starting nodes Xray core")
    with GetDB() as db:
        dbnodes = crud.get_nodes(db=db, enabled=True)
        node_ids = [dbnode.id for dbnode in dbnodes]
        for dbnode in dbnodes:
            crud.update_node_status(db, dbnode, NodeStatus.connecting)

    for node_id in node_ids:
        xray.operations.connect_node(node_id, config)

    scheduler.add_job(core_health_check, 'interval',
                      seconds=JOB_CORE_HEALTH_CHECK_INTERVAL,
                      coalesce=True, max_instances=1)


@app.on_event("shutdown")
def app_shutdown():
    logger.info("Stopping main Xray core")
    xray.core.stop()
    logger.info("Leaving remote node Xray cores running while the control plane shuts down")
