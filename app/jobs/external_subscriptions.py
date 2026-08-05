"""Low-frequency refresh scheduler for encrypted external subscriptions."""

import secrets

from app import logger, scheduler
from app.db import GetDB
from app.services import external_subscriptions


@scheduler.scheduled_job(
    "interval",
    seconds=300,
    coalesce=True,
    max_instances=1,
)
def refresh_due_external_subscriptions() -> None:
    try:
        with GetDB() as db:
            source_ids = external_subscriptions.due_source_ids(db, limit=50)
    except Exception:
        logger.error(
            "External subscription refresh scan internal error: event_id=%s",
            secrets.token_hex(8),
        )
        return

    for source_id in source_ids:
        try:
            with GetDB() as db:
                external_subscriptions.refresh_source(
                    db,
                    source_id,
                    scheduled=True,
                )
        except external_subscriptions.ExternalSubscriptionError as exc:
            # Never log the exception object: network exceptions can embed
            # a write-only URL. Stable codes plus source IDs are sufficient.
            logger.warning(
                "External subscription refresh failed: source_id=%s code=%s",
                source_id,
                exc.code,
            )
        except Exception:
            event_id = secrets.token_hex(8)
            logger.error(
                "External subscription refresh internal error: source_id=%s event_id=%s",
                source_id,
                event_id,
            )
