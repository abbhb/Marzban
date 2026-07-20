"""Security and lifecycle tests for MGMA temporary subscriptions.

The suite deliberately uses only :mod:`unittest` from the standard library as
its test runner.  Marzban's normal runtime dependencies still need to be
installed; no pytest-only fixture or plugin is required.
"""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.base import Base
from app.db import crud
from app.db.models import Admin, MgmaSettings, Proxy, User
from app.dependencies import get_validated_sub, get_validated_user
from app.models.admin import Admin as AdminSchema
from app.models.mgma import MgmaSettingsUpdate
from app.models.proxy import ProxyTypes, VLESSSettings
from app.models.user import UserDataLimitResetStrategy, UserStatus
from app.routers import mgma as mgma_router
from app.services.mgma import (
    MgmaConfigurationError,
    MgmaTokenRejected,
    MgmaUserIneligible,
    _parse_cidrs,
    build_public_subscription_url,
    digest_token,
    get_real_client_ip,
    issue_token,
    pepper_is_configured,
    require_token_pepper,
    source_allowed,
    validate_token,
)
from app.utils.jwt import create_subscription_token


UTC = timezone.utc
TEST_PEPPER = "mgma-test-pepper-which-is-longer-than-thirty-two-bytes"


def _request(*, client, x_real_ip=None, x_forwarded_for=None) -> Request:
    """Build the smallest ASGI HTTP request needed by ``get_real_client_ip``."""

    headers = []
    if x_real_ip is not None:
        headers.append((b"x-real-ip", x_real_ip.encode("ascii")))
    if x_forwarded_for is not None:
        headers.append((b"x-forwarded-for", x_forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/sub/mgma",
            "raw_path": b"/sub/mgma",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": client,
            "server": ("panel.example", 443),
        }
    )


class MgmaDatabaseTestCase(unittest.TestCase):
    """Fresh file-backed SQLite database for every test."""

    def setUp(self) -> None:
        self._env = patch.dict(os.environ, {"MGMA_TOKEN_PEPPER": TEST_PEPPER})
        self._env.start()
        self.addCleanup(self._env.stop)

        self._tempdir = tempfile.TemporaryDirectory(prefix="marzban-mgma-test-")
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

        # Public subscription guards now materialize a complete immutable user
        # snapshot before their final generation check, including proxies,
        # inbound exclusions, and lifetime usage relations.
        Base.metadata.create_all(self.engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.settings = MgmaSettings(
            id=1,
            mode="dual",
            ttl_seconds=180,
            single_use=False,
            source_mode="any",
            custom_cidrs=[],
        )
        self.db.add(self.settings)
        self.db.commit()

    def create_user(self, username: str = "alice", **overrides) -> User:
        values = {
            "username": username,
            "status": UserStatus.active,
            "used_traffic": 0,
            "data_limit": None,
            "data_limit_reset_strategy": UserDataLimitResetStrategy.no_reset,
            "expire": None,
            "created_at": datetime.now(UTC).replace(tzinfo=None),
        }
        values.update(overrides)
        user = User(**values)
        user.proxies.append(
            Proxy(
                type=ProxyTypes.VLESS,
                settings=VLESSSettings().dict(no_obj=True),
            )
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def assert_token_rejected(self, token: str, **kwargs) -> None:
        with self.assertRaises(MgmaTokenRejected):
            validate_token(self.db, token, "203.0.113.9", **kwargs)


class TokenLifecycleTests(MgmaDatabaseTestCase):
    def test_each_user_has_a_stable_random_subscription_path_token(self) -> None:
        alice = self.create_user("alice")
        bob = self.create_user("bob")

        self.assertRegex(alice.subscription_token, re.compile(r"^[A-Za-z0-9_-]{43}$"))
        self.assertRegex(bob.subscription_token, re.compile(r"^[A-Za-z0-9_-]{43}$"))
        self.assertNotEqual(alice.subscription_token, bob.subscription_token)

        persisted = self.db.get(User, alice.id)
        self.assertEqual(alice.subscription_token, persisted.subscription_token)

    def test_reissuing_mgma_changes_only_the_query_bearer(self) -> None:
        user = self.create_user()
        stable_token = user.subscription_token
        first = issue_token(self.db, user)
        first_url = build_public_subscription_url(
            user.subscription_token,
            first.token,
            base_url="https://panel.example",
        )
        second = issue_token(self.db, user)
        second_url = build_public_subscription_url(
            user.subscription_token,
            second.token,
            base_url="https://panel.example",
        )

        first_parts = urlsplit(first_url)
        second_parts = urlsplit(second_url)
        self.assertEqual(f"/sub/{stable_token}/", first_parts.path)
        self.assertEqual(first_parts.path, second_parts.path)
        self.assertNotEqual(
            parse_qs(first_parts.query)["token"],
            parse_qs(second_parts.query)["token"],
        )
        self.assertEqual(stable_token, user.subscription_token)

    def test_pepper_status_uses_the_same_utf8_byte_boundary_as_issuance(self) -> None:
        with patch.dict(os.environ, {"MGMA_TOKEN_PEPPER": "短" * 10}):
            self.assertFalse(pepper_is_configured())  # 30 UTF-8 bytes
            with self.assertRaises(MgmaConfigurationError):
                require_token_pepper()

        with patch.dict(os.environ, {"MGMA_TOKEN_PEPPER": "够" * 11}):
            self.assertTrue(pepper_is_configured())  # 33 UTF-8 bytes
            self.assertEqual("够" * 11, require_token_pepper())

    def test_cleartext_token_is_not_persisted_and_digest_is_sha256_hex(self) -> None:
        user = self.create_user()
        issued = issue_token(self.db, user)

        persisted = self.db.execute(
            select(
                User.sub_access_token_digest,
                User.sub_access_issued_at,
                User.sub_access_expires_at,
                User.sub_access_consumed_at,
            ).where(User.id == user.id)
        ).one()
        digest = persisted.sub_access_token_digest

        self.assertEqual(43, len(issued.token))
        self.assertNotEqual(issued.token, digest)
        self.assertEqual(digest_token(issued.token, TEST_PEPPER), digest)
        self.assertEqual(64, len(digest))
        self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"))
        self.assertNotIn(issued.token, repr(tuple(persisted)))

        # A raw file scan catches an accidental extra text/JSON column write,
        # not merely the intended digest-column behavior.
        self.db.close()
        self.engine.dispose()
        with open(self.database_path, "rb") as database_file:
            self.assertNotIn(issued.token.encode("ascii"), database_file.read())

    def test_latest_token_immediately_invalidates_previous_token(self) -> None:
        now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        user = self.create_user()
        first = issue_token(self.db, user, now=now)
        self.assertEqual(
            user.id,
            validate_token(
                self.db,
                first.token,
                "203.0.113.9",
                consume=False,
                now=now + timedelta(seconds=1),
            ).id,
        )

        second = issue_token(self.db, user, now=now + timedelta(seconds=2))
        self.assertNotEqual(first.token, second.token)
        self.assert_token_rejected(
            first.token,
            consume=False,
            now=now + timedelta(seconds=3),
        )
        self.assertEqual(
            user.id,
            validate_token(
                self.db,
                second.token,
                "203.0.113.9",
                consume=False,
                now=now + timedelta(seconds=3),
            ).id,
        )

    def test_revoke_subscription_clears_mgma_before_rotating_credentials(self) -> None:
        user = self.create_user()
        original_subscription_token = user.subscription_token
        issued = issue_token(self.db, user)
        vless = VLESSSettings()
        original_vless_id = vless.id
        captured = {}

        def capture_update(_db, dbuser, modified_user):
            # The MGMA fields must already be cleared when the rotated proxy
            # model reaches the shared update transaction.
            self.assertIsNone(dbuser.sub_access_token_digest)
            captured["vless_id"] = modified_user.proxies[ProxyTypes.VLESS].id
            return dbuser

        # Avoid constructing Xray inbound rows while still exercising both
        # credential rotation and the MGMA clearing order.
        with (
            patch(
                "app.db.crud.UserResponse.model_validate",
                return_value=SimpleNamespace(proxies={ProxyTypes.VLESS: vless}),
            ),
            patch("app.db.crud.update_user", side_effect=capture_update),
        ):
            revoked = crud.revoke_user_sub(self.db, user)

        self.assertIsNotNone(revoked.sub_revoked_at)
        self.assertNotEqual(original_subscription_token, revoked.subscription_token)
        self.assertIsNone(revoked.sub_access_token_digest)
        self.assertIsNone(revoked.sub_access_issued_at)
        self.assertIsNone(revoked.sub_access_expires_at)
        self.assertIsNone(revoked.sub_access_consumed_at)
        self.assertNotEqual(original_vless_id, captured["vless_id"])
        self.assert_token_rejected(issued.token, consume=False)

    def test_mgma_bearer_must_belong_to_the_stable_path_user(self) -> None:
        alice = self.create_user("alice")
        bob = self.create_user("bob")
        issued = issue_token(self.db, alice)

        with self.assertRaises(MgmaTokenRejected):
            validate_token(
                self.db,
                issued.token,
                "203.0.113.9",
                consume=False,
                expected_user_id=bob.id,
            )
        self.assertEqual(
            alice.id,
            validate_token(
                self.db,
                issued.token,
                "203.0.113.9",
                consume=False,
                expected_user_id=alice.id,
            ).id,
        )

    def test_ttl_schema_bounds_and_exact_expiry_boundary(self) -> None:
        for ttl in (30, 900):
            with self.subTest(valid_ttl=ttl):
                model = MgmaSettingsUpdate(ttl_seconds=ttl)
                self.assertEqual(ttl, model.ttl_seconds)
        for ttl in (29, 901):
            with self.subTest(invalid_ttl=ttl):
                with self.assertRaises(ValidationError):
                    MgmaSettingsUpdate(ttl_seconds=ttl)

        self.settings.ttl_seconds = 30
        self.db.commit()
        now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        user = self.create_user()
        issued = issue_token(self.db, user, now=now)
        self.assertEqual(timedelta(seconds=30), issued.expires_at - issued.issued_at)

        # The token remains valid immediately before the deadline, and is
        # rejected at the exact deadline (not one request later).
        validate_token(
            self.db,
            issued.token,
            "203.0.113.9",
            consume=False,
            now=now + timedelta(seconds=29, microseconds=999999),
        )
        self.assert_token_rejected(
            issued.token,
            consume=False,
            now=now + timedelta(seconds=30),
        )

    def test_single_use_compare_and_set_allows_only_first_session(self) -> None:
        self.settings.single_use = True
        self.db.commit()
        now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        user = self.create_user()
        issued = issue_token(self.db, user, now=now)

        second_session = self.Session()
        self.addCleanup(second_session.close)
        first_result = validate_token(
            self.db,
            issued.token,
            "203.0.113.9",
            now=now + timedelta(seconds=1),
        )
        self.assertIsNotNone(first_result.sub_access_consumed_at)

        # A second database session reaches the conditional UPDATE, whose
        # ``consumed_at IS NULL`` predicate must produce rowcount == 0.
        with self.assertRaises(MgmaTokenRejected):
            validate_token(
                second_session,
                issued.token,
                "203.0.113.9",
                now=now + timedelta(seconds=1),
            )


class SourcePolicyTests(unittest.TestCase):
    def settings(self, mode: str, custom=()):
        return SimpleNamespace(source_mode=mode, custom_cidrs=list(custom))

    def test_any_policy_accepts_even_when_source_ip_is_unavailable(self) -> None:
        self.assertTrue(source_allowed(None, self.settings("any")))
        self.assertTrue(source_allowed("not-an-ip", self.settings("any")))

    def test_china_policy_uses_offline_china_index(self) -> None:
        china = _parse_cidrs(["1.0.1.0/24", "240e::/16"])
        with patch("app.services.mgma.load_china_cidr_index", return_value=china):
            self.assertTrue(source_allowed("1.0.1.42", self.settings("china")))
            self.assertTrue(source_allowed("240e::1", self.settings("china")))
            self.assertFalse(source_allowed("8.8.8.8", self.settings("china")))

    def test_custom_policy_accepts_only_configured_ipv4_or_ipv6_cidrs(self) -> None:
        settings = self.settings("custom", ["198.51.100.0/24", "2001:db8::/32"])
        self.assertTrue(source_allowed("198.51.100.7", settings))
        self.assertTrue(source_allowed("2001:db8::7", settings))
        self.assertFalse(source_allowed("203.0.113.7", settings))
        self.assertFalse(source_allowed(None, settings))

    def test_china_or_custom_is_a_union_and_other_sources_fail_closed(self) -> None:
        china = _parse_cidrs(["1.0.1.0/24"])
        settings = self.settings("china_or_custom", ["198.51.100.0/24"])
        with patch("app.services.mgma.load_china_cidr_index", return_value=china):
            self.assertTrue(source_allowed("1.0.1.9", settings))
            self.assertTrue(source_allowed("198.51.100.9", settings))
            self.assertFalse(source_allowed("203.0.113.9", settings))
            self.assertFalse(source_allowed("invalid", settings))


class RealClientIPTests(unittest.TestCase):
    def test_uds_trusts_only_nginx_overwritten_x_real_ip(self) -> None:
        request = _request(
            client=None,
            x_real_ip="1.0.1.8",
            x_forwarded_for="198.51.100.99, 203.0.113.99",
        )
        self.assertEqual("1.0.1.8", get_real_client_ip(request))

        no_real_ip = _request(
            client=None,
            x_forwarded_for="1.0.1.8",
        )
        self.assertIsNone(get_real_client_ip(no_real_ip))

    def test_tcp_uses_peer_and_ignores_all_forged_forwarding_headers(self) -> None:
        request = _request(
            client=("203.0.113.8", 54321),
            x_real_ip="1.0.1.8",
            x_forwarded_for="1.0.1.9",
        )
        self.assertEqual("203.0.113.8", get_real_client_ip(request))


class EligibilityTests(MgmaDatabaseTestCase):
    def test_issue_gate_rejects_bad_status_expiry_and_data_limit(self) -> None:
        now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        cases = (
            ("disabled", {"status": UserStatus.disabled}),
            ("expired-status", {"status": UserStatus.expired}),
            ("limited-status", {"status": UserStatus.limited}),
            ("expired-time", {"expire": int(now.timestamp())}),
            ("data-limit", {"data_limit": 100, "used_traffic": 100}),
        )
        for index, (label, values) in enumerate(cases):
            with self.subTest(label=label):
                user = self.create_user(f"blocked{index}", **values)
                with self.assertRaises(MgmaUserIneligible):
                    issue_token(self.db, user, now=now)

        on_hold = self.create_user(
            "onhold-ok",
            status=UserStatus.on_hold,
            on_hold_expire_duration=3600,
        )
        issued = issue_token(self.db, on_hold, now=now)
        self.assertEqual(
            on_hold.id,
            validate_token(
                self.db,
                issued.token,
                "203.0.113.9",
                consume=False,
                now=now + timedelta(seconds=1),
            ).id,
        )

        zero_means_unlimited = self.create_user(
            "zero-unlimited",
            expire=0,
            data_limit=0,
        )
        issued = issue_token(self.db, zero_means_unlimited, now=now)
        self.assertEqual(
            zero_means_unlimited.id,
            validate_token(
                self.db,
                issued.token,
                "203.0.113.9",
                consume=False,
                now=now + timedelta(seconds=1),
            ).id,
        )

    def test_fetch_gate_rechecks_status_expiry_and_data_limit(self) -> None:
        now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        user = self.create_user()
        issued = issue_token(self.db, user, now=now)

        user.status = UserStatus.disabled
        self.db.commit()
        self.assert_token_rejected(issued.token, consume=False, now=now + timedelta(seconds=1))

        user.status = UserStatus.active
        user.expire = int(now.timestamp()) + 1
        self.db.commit()
        self.assert_token_rejected(issued.token, consume=False, now=now + timedelta(seconds=1))

        user.expire = None
        user.data_limit = 100
        user.used_traffic = 100
        self.db.commit()
        self.assert_token_rejected(issued.token, consume=False, now=now + timedelta(seconds=1))


class DependencyModeTests(MgmaDatabaseTestCase):
    def test_ephemeral_mode_requires_mgma_query_for_stable_path(self) -> None:
        self.settings.mode = "ephemeral"
        self.db.commit()
        user = self.create_user()
        request = _request(client=("203.0.113.9", 12345))
        with self.assertRaises(HTTPException) as caught:
            get_validated_sub(
                subscription_token=user.subscription_token,
                token=None,
                request=request,
                db=self.db,
            )
        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual("Not Found", caught.exception.detail)
        self.assertEqual("private, no-store, max-age=0", caught.exception.headers["Cache-Control"])

    def test_valid_query_authorizes_only_its_matching_stable_path(self) -> None:
        self.settings.mode = "ephemeral"
        self.db.commit()
        alice = self.create_user("alice")
        bob = self.create_user("bob")
        issued = issue_token(self.db, alice)
        request = _request(client=("203.0.113.9", 12345))

        resolved = get_validated_sub(
            subscription_token=alice.subscription_token,
            token=issued.token,
            request=request,
            db=self.db,
        )
        self.assertEqual(alice.id, resolved.id)
        self.assertTrue(request.state.mgma_authorized)

        mismatch_request = _request(client=("203.0.113.9", 12345))
        with self.assertRaises(HTTPException) as caught:
            get_validated_sub(
                subscription_token=bob.subscription_token,
                token=issued.token,
                request=mismatch_request,
                db=self.db,
            )
        self.assertEqual(404, caught.exception.status_code)

    def test_generation_change_after_snapshot_rejects_old_authorization(self) -> None:
        user = self.create_user()
        issued = issue_token(self.db, user)
        original_path = user.subscription_token

        def rotate_generation(_dbuser):
            user.subscription_token = secrets.token_urlsafe(32)
            user.sub_access_token_digest = digest_token(secrets.token_urlsafe(32))
            self.db.commit()
            return SimpleNamespace(username=user.username)

        with patch(
            "app.dependencies.UserResponse.model_validate",
            side_effect=rotate_generation,
        ):
            with self.assertRaises(HTTPException) as caught:
                get_validated_sub(
                    subscription_token=original_path,
                    token=issued.token,
                    request=_request(client=("203.0.113.9", 12345)),
                    db=self.db,
                )
        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual(
            "private, no-store, max-age=0",
            caught.exception.headers["Cache-Control"],
        )

    def test_invalid_query_never_falls_back_to_dual_long_lived_access(self) -> None:
        user = self.create_user()
        request = _request(client=("203.0.113.9", 12345))
        with self.assertRaises(HTTPException) as caught:
            get_validated_sub(
                subscription_token=user.subscription_token,
                token="invalid-temporary-token",
                request=request,
                db=self.db,
            )
        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual("private, no-store, max-age=0", caught.exception.headers["Cache-Control"])

    def test_expired_query_never_falls_back_to_dual_long_lived_access(self) -> None:
        user = self.create_user()
        issued = issue_token(self.db, user)
        user.sub_access_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        self.db.commit()
        request = _request(client=("203.0.113.9", 12345))

        with self.assertRaises(HTTPException) as caught:
            get_validated_sub(
                subscription_token=user.subscription_token,
                token=issued.token,
                request=request,
                db=self.db,
            )
        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual("private, no-store, max-age=0", caught.exception.headers["Cache-Control"])

    def test_stable_path_without_query_is_rejected_in_every_mode(self) -> None:
        user = self.create_user()
        for mode in ("legacy", "dual", "ephemeral"):
            with self.subTest(mode=mode):
                self.settings.mode = mode
                self.db.commit()
                request = _request(client=("203.0.113.9", 12345))
                with self.assertRaises(HTTPException) as caught:
                    get_validated_sub(
                        subscription_token=user.subscription_token,
                        token=None,
                        request=request,
                        db=self.db,
                    )
                self.assertEqual(404, caught.exception.status_code)
                self.assertEqual(
                    "private, no-store, max-age=0",
                    caught.exception.headers["Cache-Control"],
                )

    def test_only_pre_upgrade_signed_path_keeps_no_query_compatibility(self) -> None:
        user = self.create_user()
        with patch("app.utils.jwt.get_secret_key", return_value="legacy-test-secret"):
            legacy_token = create_subscription_token(user.username)

            for mode in ("legacy", "dual"):
                with self.subTest(mode=mode):
                    self.settings.mode = mode
                    self.db.commit()
                    request = _request(client=("203.0.113.9", 12345))
                    resolved = get_validated_sub(
                        subscription_token=legacy_token,
                        token=None,
                        request=request,
                        db=self.db,
                    )
                    self.assertEqual(user.id, resolved.id)
                    self.assertFalse(request.state.mgma_authorized)

            self.settings.mode = "ephemeral"
            self.db.commit()
            with self.assertRaises(HTTPException) as caught:
                get_validated_sub(
                    subscription_token=legacy_token,
                    token=None,
                    request=_request(client=("203.0.113.9", 12345)),
                    db=self.db,
                )
        self.assertEqual(404, caught.exception.status_code)

    def test_same_second_regeneration_revokes_ceil_timestamp_legacy_path(self) -> None:
        base_timestamp = 1_800_000_000
        user = self.create_user(
            created_at=datetime.fromtimestamp(base_timestamp - 60, UTC).replace(
                tzinfo=None
            )
        )
        user.sub_revoked_at = datetime.fromtimestamp(
            base_timestamp + 0.2,
            UTC,
        ).replace(tzinfo=None)
        self.db.commit()

        with (
            patch("app.utils.jwt.get_secret_key", return_value="legacy-test-secret"),
            patch("app.utils.jwt.time.time", return_value=base_timestamp + 0.1),
        ):
            legacy_token = create_subscription_token(user.username)
            with self.assertRaises(HTTPException) as caught:
                get_validated_sub(
                    subscription_token=legacy_token,
                    token=None,
                    request=_request(client=("203.0.113.9", 12345)),
                    db=self.db,
                )
        self.assertEqual(404, caught.exception.status_code)

    def test_html_query_is_rejected_without_consuming_single_use_token(self) -> None:
        self.settings.mode = "ephemeral"
        self.settings.single_use = True
        self.db.commit()
        user = self.create_user()
        issued = issue_token(self.db, user)
        request = _request(client=("203.0.113.9", 12345))
        request.scope["headers"] = [(b"accept", b"text/html")]

        with self.assertRaises(HTTPException) as caught:
            get_validated_sub(
                subscription_token=user.subscription_token,
                token=issued.token,
                request=request,
                db=self.db,
            )
        self.assertEqual(404, caught.exception.status_code)
        validate_token(
            self.db,
            issued.token,
            "203.0.113.9",
            consume=False,
        )

    def test_legacy_route_applies_source_policy_before_decoding_token(self) -> None:
        self.settings.mode = "dual"
        self.settings.source_mode = "custom"
        self.settings.custom_cidrs = ["198.51.100.0/24"]
        self.db.commit()
        denied_request = _request(client=("203.0.113.9", 12345))

        with patch("app.dependencies.get_subscription_payload") as decode:
            with self.assertRaises(HTTPException) as caught:
                get_validated_sub(
                    subscription_token="legacy-permanent-token",
                    token=None,
                    request=denied_request,
                    db=self.db,
                )
        self.assertEqual(404, caught.exception.status_code)
        decode.assert_not_called()

    def test_non_owner_cannot_issue_for_another_admins_user(self) -> None:
        owner = Admin(username="owner", hashed_password="unused", is_sudo=False)
        other = Admin(username="other", hashed_password="unused", is_sudo=False)
        self.db.add_all([owner, other])
        self.db.commit()
        user = self.create_user("owned-user", admin=owner)

        with self.assertRaises(HTTPException) as caught:
            get_validated_user(
                username=user.username,
                admin=AdminSchema.model_validate(other),
                db=self.db,
            )
        self.assertEqual(403, caught.exception.status_code)


class RouteRegistrationTests(unittest.TestCase):
    def test_exact_mgma_routes_precede_legacy_token_catch_all(self) -> None:
        from app import app as marzban_app

        paths = [route.path for route in marzban_app.routes]
        self.assertLess(paths.index("/sub/mgma"), paths.index("/sub/{subscription_token}"))

    def test_settings_read_and_write_both_require_sudo_dependency(self) -> None:
        from app import app as marzban_app

        routes = [
            route
            for route in marzban_app.routes
            if route.path == "/api/subscription/settings"
        ]
        self.assertEqual(2, len(routes))
        for route in routes:
            calls = [dependency.call for dependency in route.dependant.dependencies]
            self.assertIn(AdminSchema.check_sudo_admin, calls)

    def test_every_legacy_subscription_variant_uses_the_shared_guard(self) -> None:
        from app import app as marzban_app

        guarded_paths = {
            "/sub/{subscription_token}",
            "/sub/{subscription_token}/info",
            "/sub/{subscription_token}/usage",
            "/sub/{subscription_token}/{client_type}",
        }
        seen = set()
        for route in marzban_app.routes:
            if route.path not in guarded_paths:
                continue
            calls = [dependency.call for dependency in route.dependant.dependencies]
            self.assertIn(get_validated_sub, calls, route.path)
            seen.add(route.path)
        self.assertEqual(guarded_paths, seen)


class PublicRouteTests(MgmaDatabaseTestCase):
    def call_public_route(
        self,
        token: str = "",
        *,
        accept: str = "application/octet-stream",
        user_agent: str = "mgma-test",
    ):
        request = _request(
            client=("203.0.113.9", 54321),
        )
        # ``Request.headers`` is immutable, so build the requested Accept value
        # into a fresh scope without relying on an HTTP client test dependency.
        request.scope["headers"] = [
            (b"accept", accept.encode("ascii")),
            (b"user-agent", user_agent.encode("ascii")),
        ]
        return mgma_router.mgma_subscription(
            request=request,
            token=token,
            user_agent=user_agent,
            db=self.db,
        )

    def rejection_fingerprint(self, token: str = "", *, accept: str = "application/octet-stream"):
        try:
            self.call_public_route(token, accept=accept)
        except HTTPException as exc:
            return exc.status_code, {"detail": exc.detail}
        self.fail("public route unexpectedly accepted a rejected token")

    def test_missing_malformed_and_unknown_tokens_have_identical_404(self) -> None:
        unknown = secrets.token_urlsafe(32)
        fingerprints = (
            self.rejection_fingerprint(),
            self.rejection_fingerprint("not-a-valid-token"),
            self.rejection_fingerprint(unknown),
        )
        self.assertEqual(
            ((404, {"detail": "Not Found"}),) * len(fingerprints),
            tuple(fingerprints),
        )

    def test_rejected_subscription_has_no_store_headers(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.call_public_route("not-a-valid-token")

        self.assertEqual(404, raised.exception.status_code)
        self.assertEqual(mgma_router.NO_STORE_HEADERS, raised.exception.headers)

    def test_html_accept_is_opaque_404_even_for_valid_token(self) -> None:
        issued = issue_token(self.db, self.create_user())
        fingerprint = self.rejection_fingerprint(
            issued.token,
            accept="text/html,application/xhtml+xml",
        )
        self.assertEqual((404, {"detail": "Not Found"}), fingerprint)

        # Rejecting a browser-rendered page must not itself consume the token.
        validate_token(
            self.db,
            issued.token,
            "203.0.113.9",
            consume=False,
        )

    def test_legacy_alias_rechecks_generation_after_materializing_snapshot(self) -> None:
        user = self.create_user()
        issued = issue_token(self.db, user)

        def rotate_generation(_dbuser):
            user.subscription_token = secrets.token_urlsafe(32)
            user.sub_access_token_digest = digest_token(secrets.token_urlsafe(32))
            self.db.commit()
            return SimpleNamespace(username=user.username)

        with patch.object(
            mgma_router.UserResponse,
            "model_validate",
            side_effect=rotate_generation,
        ):
            with self.assertRaises(HTTPException) as caught:
                self.call_public_route(issued.token)
        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual(mgma_router.NO_STORE_HEADERS, caught.exception.headers)

    def test_public_subscription_has_no_store_and_never_reflects_token(self) -> None:
        issued = issue_token(self.db, self.create_user())
        rendered_user = SimpleNamespace(
            username="alice",
            used_traffic=0,
            data_limit=None,
            expire=None,
            proxies={},
            inbounds={},
        )
        with (
            patch.object(
                mgma_router.UserResponse,
                "model_validate",
                return_value=rendered_user,
            ),
            patch(
                "app.routers.subscription.generate_subscription",
                return_value="temporary-node-config",
            ),
        ):
            response = self.call_public_route(issued.token)

        self.assertEqual(200, response.status_code)
        self.assertEqual(b"temporary-node-config", response.body)
        headers = dict(response.headers)
        self.assertEqual("private, no-store, max-age=0", headers["cache-control"])
        self.assertEqual("no-cache", headers["pragma"])
        self.assertEqual("0", headers["expires"])
        self.assertEqual("no-referrer", headers["referrer-policy"])
        self.assertEqual("noindex, nofollow, noarchive", headers["x-robots-tag"])
        self.assertNotIn("profile-web-page-url", response.headers)
        self.assertNotIn(issued.token, repr(headers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
