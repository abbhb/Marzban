"""Transactional tests for portal accounts, wallets and plan lifecycle."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.db.base import Base
from app.db.models import (
    PortalAccount,
    PortalIPBlock,
    PortalInvitationCode,
    PortalInvitationUse,
    PortalPurchase,
    PortalSecurityAttempt,
    SubscriptionPlan,
    WalletTransaction,
)
from app.models.commerce import PortalRegister, SubscriptionPlanCreate
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.dependencies import get_current_portal_account
from app.services import commerce, portal_security
from app.services.rate_limit import SlidingWindowLimiter
from app.utils.jwt import create_admin_token, create_portal_token, get_portal_payload


class CommerceDatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="marzban-commerce-test-")
        self.addCleanup(self._tempdir.cleanup)
        self.database_path = os.path.join(self._tempdir.name, "test.sqlite3")
        self.engine = create_engine(
            f"sqlite:///{self.database_path}",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        self.Session = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(self.engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

        inbounds = [
            {"tag": "HK01", "protocol": "vless"},
            {"tag": "HK01-US", "protocol": "vless"},
            {"tag": "HK02", "protocol": "vless"},
            {"tag": "HK02-US", "protocol": "vless"},
        ]
        self._xray = patch.multiple(
            commerce.xray.config,
            inbounds_by_tag={item["tag"]: item for item in inbounds},
            inbounds_by_protocol={ProxyTypes.VLESS: inbounds},
        )
        self._xray.start()
        self.addCleanup(self._xray.stop)
        self._password_hash = patch.object(
            commerce.pwd_context,
            "hash",
            side_effect=lambda password: f"bcrypt-test:{password}",
        )
        self._password_verify = patch.object(
            commerce.pwd_context,
            "verify",
            side_effect=lambda password, digest: digest == f"bcrypt-test:{password}",
        )
        self._password_hash.start()
        self._password_verify.start()
        self.addCleanup(self._password_hash.stop)
        self.addCleanup(self._password_verify.stop)

    def create_plan(
        self,
        *,
        name: str = "Standard",
        price_minor: int = 1000,
        duration_days: int = 30,
        data_limit: int = 100 * 1024**3,
        inbound_tags=None,
        is_default: bool = True,
    ) -> SubscriptionPlan:
        return commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name=name,
                description="test plan",
                price_minor=price_minor,
                duration_days=duration_days,
                data_limit=data_limit,
                inbound_tags=inbound_tags or ["HK01", "HK01-US"],
                is_default=is_default,
            ),
        )

    def register(self, username: str = "alice") -> PortalAccount:
        _invitation, code = portal_security.create_invitation(
            self.db,
            created_by="root",
            note=f"test invite for {username}",
            max_uses=1,
        )
        return commerce.register_account(
            self.db,
            PortalRegister(
                username=username,
                password="correct-horse-battery",
                invitation_code=code,
            ),
            source_ip="198.51.100.10",
        )


class AccountAndPlanTests(CommerceDatabaseTestCase):
    def test_registration_hashes_password_and_assigns_the_single_default_plan(self) -> None:
        default = self.create_plan()
        account = self.register()

        self.assertNotEqual("correct-horse-battery", account.hashed_password)
        self.assertTrue(commerce.authenticate_account(self.db, "alice", "correct-horse-battery"))
        self.assertIsNone(commerce.authenticate_account(self.db, "alice", "wrong-password"))
        self.assertEqual(default.id, account.assigned_plan_id)
        self.assertEqual([default.id], [plan.id for plan in commerce.visible_plans(account)])
        self.assertIsNone(account.user_id)

    def test_a_new_default_replaces_the_old_default_without_reassigning_existing_accounts(self) -> None:
        first = self.create_plan(name="First")
        account = self.register()
        second = self.create_plan(name="Second")
        self.db.refresh(first)

        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(first.id, account.assigned_plan_id)
        self.assertEqual(second.id, self.register("bob").assigned_plan_id)

    def test_registration_rejects_an_existing_proxy_username(self) -> None:
        from app.db.models import User

        self.db.add(User(username="alice", status=UserStatus.active, used_traffic=0))
        self.db.commit()
        with self.assertRaises(commerce.AccountExists):
            self.register()


class InvitationSecurityTests(CommerceDatabaseTestCase):
    def register_with_code(
        self,
        username: str,
        code: str,
        *,
        now: datetime | None = None,
    ) -> PortalAccount:
        return commerce.register_account(
            self.db,
            PortalRegister(
                username=username,
                password="correct-horse-battery",
                invitation_code=code,
            ),
            source_ip="198.51.100.20",
            now=now,
        )

    def test_one_time_invitation_is_hashed_consumed_once_and_audited(self) -> None:
        invitation, code = portal_security.create_invitation(
            self.db,
            created_by="root",
            note="one time",
            max_uses=1,
        )

        self.assertNotEqual(code, invitation.code_digest)
        self.assertNotIn(code, repr(invitation.__dict__))
        account = self.register_with_code("alice", code)
        with self.assertRaises(portal_security.InvitationUnavailable):
            self.register_with_code("bob", code)
        self.db.rollback()

        self.db.refresh(invitation)
        self.assertEqual(1, invitation.use_count)
        use = self.db.query(PortalInvitationUse).one()
        self.assertEqual(account.id, use.account_id)
        self.assertEqual("198.51.100.20", use.source_ip)

    def test_scheduled_n_use_and_permanent_unlimited_invitations(self) -> None:
        start = datetime(2026, 7, 14, 1, 0, 0)
        invitation, code = portal_security.create_invitation(
            self.db,
            created_by="root",
            valid_from=start,
            expires_at=start + timedelta(hours=1),
            max_uses=2,
        )
        with self.assertRaises(portal_security.InvitationUnavailable):
            self.register_with_code("early", code, now=start - timedelta(seconds=1))
        self.db.rollback()
        self.register_with_code("alice", code, now=start)
        self.register_with_code("bob", code, now=start + timedelta(minutes=30))
        with self.assertRaises(portal_security.InvitationUnavailable):
            self.register_with_code("charlie", code, now=start + timedelta(minutes=31))
        self.db.rollback()
        self.db.refresh(invitation)
        self.assertEqual(2, invitation.use_count)

        _unlimited, permanent_code = portal_security.create_invitation(
            self.db,
            created_by="root",
            max_uses=None,
            expires_at=None,
        )
        self.register_with_code("dora", permanent_code, now=start)
        self.register_with_code("eve", permanent_code, now=start + timedelta(days=3650))

    def test_duplicate_username_does_not_consume_the_invitation(self) -> None:
        self.register("alice")
        invitation, code = portal_security.create_invitation(
            self.db,
            created_by="root",
            max_uses=1,
        )
        with self.assertRaises(commerce.AccountExists):
            self.register_with_code("alice", code)
        self.db.refresh(invitation)
        self.assertEqual(0, invitation.use_count)

    def test_automatic_block_has_reason_expiry_and_can_be_revoked(self) -> None:
        portal_security.update_security_settings(
            self.db,
            {
                "auto_block_enabled": True,
                "login_failure_limit": 3,
                "login_window_seconds": 300,
                "registration_failure_limit": 4,
                "registration_window_seconds": 600,
                "auto_block_seconds": 3600,
            },
        )
        now = datetime(2026, 7, 14, 2, 0, 0)
        for offset in range(2):
            self.assertIsNone(
                portal_security.record_failure(
                    self.db,
                    source_ip="203.0.113.8",
                    kind="portal_login",
                    now=now + timedelta(seconds=offset),
                )
            )
        block = portal_security.record_failure(
            self.db,
            source_ip="203.0.113.8",
            kind="portal_login",
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(block)
        self.assertEqual("203.0.113.8/32", block.network)
        self.assertIn("3 failed portal login", block.reason)
        self.assertEqual(now + timedelta(seconds=3602), block.expires_at)
        self.assertEqual(block.id, portal_security.find_active_block(self.db, "203.0.113.8", now=now).id)
        self.assertIsNone(
            portal_security.find_active_block(
                self.db,
                "203.0.113.8",
                now=now + timedelta(hours=2),
            )
        )

        portal_security.revoke_block(self.db, block, revoked_by="root", now=now)
        self.assertFalse(block.is_active)
        self.assertEqual(0, self.db.query(PortalSecurityAttempt).count())

    def test_manual_cidr_block_matches_addresses_and_preserves_reason(self) -> None:
        block = portal_security.add_block(
            self.db,
            network="198.51.100.7/24",
            reason="credential stuffing source range",
            source="manual",
            created_by="root",
        )
        self.assertEqual("198.51.100.0/24", block.network)
        self.assertEqual("credential stuffing source range", block.reason)
        self.assertIsNotNone(portal_security.find_active_block(self.db, "198.51.100.99"))
        self.assertIsNone(portal_security.find_active_block(self.db, "203.0.113.99"))

    def test_persistent_failure_counter_cardinality_is_bounded(self) -> None:
        now = datetime(2026, 7, 14, 3, 0, 0)
        with patch.object(portal_security, "MAX_ATTEMPT_ROWS", 2):
            for index in range(3):
                portal_security.record_failure(
                    self.db,
                    source_ip=f"203.0.113.{index + 1}",
                    kind="portal_login",
                    now=now + timedelta(seconds=index),
                )
        rows = self.db.query(PortalSecurityAttempt).order_by(PortalSecurityAttempt.source_ip).all()
        self.assertEqual(["203.0.113.2", "203.0.113.3"], [row.source_ip for row in rows])


class WalletAndPurchaseTests(CommerceDatabaseTestCase):
    def test_recharge_and_purchase_are_audited_and_create_only_authorized_nodes(self) -> None:
        plan = self.create_plan()
        account = self.register()
        account = commerce.recharge_wallet(
            self.db,
            account,
            amount_minor=2500,
            actor_admin="root",
            note="manual recharge",
            idempotency_key="recharge-0001",
        )

        result = commerce.purchase_plan(
            self.db,
            account,
            plan_id=plan.id,
            idempotency_key="purchase-0001",
            now=datetime(2026, 7, 13, 12, 0, 0),
        )

        self.assertEqual(1500, result.account.wallet_balance_minor)
        self.assertTrue(result.created_user)
        self.assertEqual(UserStatus.active, result.user.status)
        self.assertEqual(plan.data_limit, result.user.data_limit)
        self.assertEqual(
            ["HK01", "HK01-US"],
            result.user.inbounds[ProxyTypes.VLESS],
        )
        self.assertEqual(2, self.db.query(WalletTransaction).count())
        amounts = [row.amount_minor for row in self.db.query(WalletTransaction).order_by(WalletTransaction.id)]
        self.assertEqual([2500, -1000], amounts)
        self.assertEqual(1, self.db.query(PortalPurchase).count())

    def test_insufficient_balance_rolls_back_every_purchase_side_effect(self) -> None:
        plan = self.create_plan(price_minor=2000)
        account = self.register()
        account = commerce.recharge_wallet(
            self.db,
            account,
            amount_minor=500,
            actor_admin="root",
            note=None,
            idempotency_key="recharge-0002",
        )

        with self.assertRaises(commerce.InsufficientBalance):
            commerce.purchase_plan(
                self.db,
                account,
                plan_id=plan.id,
                idempotency_key="purchase-0002",
            )

        account = commerce.get_account(self.db, account.id)
        self.assertEqual(500, account.wallet_balance_minor)
        self.assertIsNone(account.user_id)
        self.assertIsNone(account.subscription)
        self.assertEqual(0, self.db.query(PortalPurchase).count())

    def test_idempotency_key_returns_the_first_result_without_a_second_debit(self) -> None:
        plan = self.create_plan()
        account = commerce.recharge_wallet(
            self.db,
            self.register(),
            amount_minor=3000,
            actor_admin="root",
            note=None,
            idempotency_key="recharge-0003",
        )
        first = commerce.purchase_plan(
            self.db,
            account,
            plan_id=plan.id,
            idempotency_key="purchase-0003",
        )
        second = commerce.purchase_plan(
            self.db,
            commerce.get_account(self.db, account.id),
            plan_id=plan.id,
            idempotency_key="purchase-0003",
        )

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.purchase.id, second.purchase.id)
        self.assertEqual(2000, second.account.wallet_balance_minor)
        self.assertEqual(1, self.db.query(PortalPurchase).count())
        self.assertEqual(1, self.db.query(WalletTransaction).filter(WalletTransaction.kind == "purchase_debit").count())

    def test_second_purchase_overwrites_entitlement_and_preserves_vless_identity(self) -> None:
        standard = self.create_plan(name="Standard", price_minor=1000)
        premium = self.create_plan(
            name="Premium",
            price_minor=2000,
            data_limit=300 * 1024**3,
            inbound_tags=["HK01", "HK01-US", "HK02", "HK02-US"],
            is_default=False,
        )
        account = commerce.recharge_wallet(
            self.db,
            self.register(),
            amount_minor=5000,
            actor_admin="root",
            note=None,
            idempotency_key="recharge-0004",
        )
        first = commerce.purchase_plan(
            self.db,
            account,
            plan_id=standard.id,
            idempotency_key="purchase-0004",
            now=datetime(2026, 7, 1),
        )
        original_uuid = first.user.proxies[0].settings["id"]
        first.user.used_traffic = 123456
        self.db.commit()
        account = commerce.assign_plan(self.db, first.account, premium)

        second = commerce.purchase_plan(
            self.db,
            account,
            plan_id=premium.id,
            idempotency_key="purchase-0005",
            now=datetime(2026, 7, 15),
        )

        self.assertEqual(original_uuid, second.user.proxies[0].settings["id"])
        self.assertEqual(0, second.user.used_traffic)
        self.assertEqual(premium.data_limit, second.user.data_limit)
        self.assertEqual(
            ["HK01", "HK01-US", "HK02", "HK02-US"],
            second.user.inbounds[ProxyTypes.VLESS],
        )
        self.assertEqual(datetime(2026, 8, 14), second.account.subscription.expires_at)

    def test_free_plan_does_not_create_a_zero_amount_wallet_row(self) -> None:
        plan = self.create_plan(price_minor=0)
        result = commerce.purchase_plan(
            self.db,
            self.register(),
            plan_id=plan.id,
            idempotency_key="purchase-free-1",
        )
        self.assertEqual(0, result.account.wallet_balance_minor)
        self.assertEqual(0, self.db.query(WalletTransaction).count())


class AdminLifecycleTests(CommerceDatabaseTestCase):
    def test_admin_recharge_is_idempotent_and_rejects_a_changed_amount(self) -> None:
        account = self.register()
        first = commerce.recharge_wallet(
            self.db,
            account,
            amount_minor=2000,
            actor_admin="root",
            note="manual",
            idempotency_key="recharge-idempotent-1",
        )
        second = commerce.recharge_wallet(
            self.db,
            first,
            amount_minor=2000,
            actor_admin="root",
            note="retry",
            idempotency_key="recharge-idempotent-1",
        )

        self.assertEqual(2000, second.wallet_balance_minor)
        self.assertEqual(1, self.db.query(WalletTransaction).count())
        with self.assertRaises(commerce.IdempotencyConflict):
            commerce.recharge_wallet(
                self.db,
                second,
                amount_minor=3000,
                actor_admin="root",
                note=None,
                idempotency_key="recharge-idempotent-1",
            )

    def test_admin_grant_and_renew_do_not_change_wallet_balance(self) -> None:
        plan = self.create_plan()
        account = self.register()
        grant = commerce.grant_plan(
            self.db,
            account,
            plan,
            actor_admin="root",
            idempotency_key="grant-0001",
            now=datetime(2026, 7, 1),
        )
        renewal = commerce.renew_subscription(
            self.db,
            grant.account,
            days=15,
            actor_admin="root",
            idempotency_key="renew-0001",
            now=datetime(2026, 7, 10),
        )

        self.assertEqual(0, renewal.account.wallet_balance_minor)
        self.assertEqual(datetime(2026, 8, 15), renewal.account.subscription.expires_at)
        self.assertEqual(
            ["admin_grant", "admin_renewal"],
            [row.kind for row in self.db.query(PortalPurchase).order_by(PortalPurchase.id)],
        )
        self.assertEqual(0, self.db.query(WalletTransaction).count())

        replay = commerce.renew_subscription(
            self.db,
            renewal.account,
            days=15,
            actor_admin="root",
            idempotency_key="renew-0001",
            now=datetime(2026, 7, 11),
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(datetime(2026, 8, 15), replay.account.subscription.expires_at)
        self.assertEqual(2, self.db.query(PortalPurchase).count())

    def test_disable_marks_both_subscription_and_proxy_user(self) -> None:
        plan = self.create_plan()
        grant = commerce.grant_plan(
            self.db,
            self.register(),
            plan,
            actor_admin="root",
            idempotency_key="grant-0002",
        )
        user = commerce.disable_subscription(self.db, grant.account)

        self.assertEqual(UserStatus.disabled, user.status)
        self.assertIsNotNone(grant.account.subscription.disabled_at)


class PortalTokenTests(unittest.TestCase):
    def test_portal_token_cannot_be_confused_with_an_admin_token(self) -> None:
        with patch("app.utils.jwt.get_secret_key", return_value="test-secret"):
            portal = create_portal_token(7, "alice")
            admin = create_admin_token("alice", True)

            self.assertEqual(7, get_portal_payload(portal)["account_id"])
            self.assertIsNone(get_portal_payload(admin))


class PortalDependencyTests(CommerceDatabaseTestCase):
    def test_portal_dependency_resolves_only_the_token_owner_and_rejects_admin_tokens(self) -> None:
        self.create_plan()
        alice = self.register("alice")
        bob = self.register("bob")
        with patch("app.utils.jwt.get_secret_key", return_value="test-secret"):
            alice_token = create_portal_token(alice.id, alice.username)
            bob_token = create_portal_token(bob.id, bob.username)
            admin_token = create_admin_token("root", True)

            self.assertEqual(
                alice.id,
                get_current_portal_account(db=self.db, token=alice_token).id,
            )
            self.assertEqual(
                bob.id,
                get_current_portal_account(db=self.db, token=bob_token).id,
            )
            with self.assertRaises(HTTPException):
                get_current_portal_account(db=self.db, token=admin_token)

            alice.is_active = False
            self.db.commit()
            with self.assertRaises(HTTPException):
                get_current_portal_account(db=self.db, token=alice_token)


class RateLimitTests(unittest.TestCase):
    def test_sliding_window_blocks_then_recovers_and_is_bounded(self) -> None:
        limiter = SlidingWindowLimiter(max_keys=2)

        self.assertEqual(0, limiter.hit("one", limit=2, window_seconds=10, now=0))
        self.assertEqual(0, limiter.hit("one", limit=2, window_seconds=10, now=1))
        self.assertEqual(9, limiter.hit("one", limit=2, window_seconds=10, now=1))
        self.assertEqual(0, limiter.hit("one", limit=2, window_seconds=10, now=10))
        limiter.hit("two", limit=1, window_seconds=10, now=10)
        limiter.hit("three", limit=1, window_seconds=10, now=10)
        self.assertNotIn("one", limiter._events)

    def test_reset_clears_only_the_selected_key(self) -> None:
        limiter = SlidingWindowLimiter()
        limiter.hit("account", limit=1, window_seconds=60, now=0)
        limiter.hit("ip", limit=1, window_seconds=60, now=0)
        limiter.reset("account")

        self.assertEqual(0, limiter.hit("account", limit=1, window_seconds=60, now=1))
        self.assertEqual(59, limiter.hit("ip", limit=1, window_seconds=60, now=1))


if __name__ == "__main__":
    unittest.main()
