#!/usr/bin/env python3
"""Reconcile current plan node grants without exposing account identities."""

from __future__ import annotations

import argparse

from app.db import GetDB
from app.db.models import PortalSubscription, SubscriptionPlan
from app.services import commerce


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with GetDB() as db:
        plans = db.query(SubscriptionPlan).order_by(SubscriptionPlan.id).all()
        drifted = 0
        affected_users = 0
        for plan in plans:
            subscriptions = (
                db.query(PortalSubscription)
                .filter(PortalSubscription.plan_id == plan.id)
                .all()
            )
            drifted += sum(
                1
                for subscription in subscriptions
                if list(subscription.inbound_tags or []) != list(plan.inbound_tags or [])
            )
            if args.apply:
                affected_users += len(
                    commerce.reconcile_plan_entitlements(db, plan, commit=False)
                )

        if args.apply:
            db.commit()
        else:
            db.rollback()

    mode = "applied" if args.apply else "check"
    print(
        f"mode={mode} plans={len(plans)} drifted_subscriptions={drifted} "
        f"affected_users={affected_users}"
    )


if __name__ == "__main__":
    main()
