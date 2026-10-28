"""Remove stale local plan references, then sync affected runtime users."""
from datetime import datetime, timedelta, timezone
import secrets

from app import logger, scheduler, xray
from app.db import GetDB
from app.db.models import SubscriptionPlan, User
from app.models.user import UserStatus
from app.services.commerce import cleanup_plan_local_nodes

_pending_users = set()


@scheduler.scheduled_job("interval", seconds=300, coalesce=True, max_instances=1,
                         id="cleanup_stale_plan_nodes",
                         next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45))
def cleanup_stale_plan_nodes():
    last_id, cleaned = 0, 0
    while True:
        try:
            with GetDB() as db:
                ids = [row[0] for row in db.query(SubscriptionPlan.id)
                       .filter(SubscriptionPlan.id > last_id).order_by(SubscriptionPlan.id).limit(100)]
        except Exception:
            logger.error("Plan node cleanup scan failed: event_id=%s", secrets.token_hex(8))
            break
        if not ids:
            break
        for plan_id in ids:
            try:
                with GetDB() as db:
                    changed, users = cleanup_plan_local_nodes(db, plan_id)
                cleaned += int(changed)
                _pending_users.update(user_id for user_id, _status in users)
            except Exception:
                logger.error("Plan node cleanup failed: plan_id=%s event_id=%s", plan_id, secrets.token_hex(8))
        last_id = ids[-1]
    for user_id in list(_pending_users):
        try:
            with GetDB() as db:
                row = db.query(User.status).filter(User.id == user_id).first()
            if row:
                operation = (xray.operations.update_user_by_id
                             if row[0] in (UserStatus.active, UserStatus.on_hold)
                             else xray.operations.remove_user_by_id)
                operation(user_id=user_id)
            _pending_users.discard(user_id)
        except Exception:
            logger.error("Plan node cleanup user sync failed: user_id=%s event_id=%s", user_id, secrets.token_hex(8))
    if cleaned or _pending_users:
        logger.info("Plan node cleanup: cleaned_plans=%s pending_users=%s", cleaned, len(_pending_users))
