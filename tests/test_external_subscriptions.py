"""Security and lifecycle tests for imported external Clash subscriptions.

The fixtures use synthetic host names and credentials only.  They never read
or contact an operator's real subscription URL or local Clash profile.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.db.base import Base
from app.db.models import (
    ExternalSubscriptionBudgetLock,
    ExternalSubscriptionNode,
    ExternalSubscriptionSource,
    PortalAccount,
    PortalSubscription,
    SubscriptionPlan,
    SubscriptionPlanExternalSelection,
    User,
)
from app.models.admin import Admin as AdminSchema
from app.models.commerce import (
    ExternalSelectionInput,
    ExternalSubscriptionNodeResponse,
    ExternalSubscriptionSourceResponse,
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
)
from app.models.user import UserDataLimitResetStrategy, UserStatus
from app.routers import commerce as commerce_router
from app.routers import mgma as mgma_router
from app.routers import subscription as subscription_router
from app.services import commerce, external_subscriptions


TEST_ENCRYPTION_KEY = "external-subscription-test-key-is-long-enough-2026"
CANARY_SECRET = "external-canary-secret-7a7b26e9"
CANARY_URL = f"https://feed.example.test/subscription?bearer={CANARY_SECRET}"


def _snapshot(*names: str, secret: str = "synthetic-node-secret") -> bytes:
    proxies = []
    for index, name in enumerate(names):
        proxies.append(
            {
                "name": name,
                "type": "vmess",
                "server": f"node-{index}.example.test",
                "port": 443,
                "uuid": f"{secret}-{index}",
                "tls": True,
            }
        )
    # JSON is a YAML subset and avoids introducing a test dependency on a YAML
    # dumper before the module under test is imported.
    return json.dumps({"proxies": proxies}, ensure_ascii=False).encode("utf-8")


class _FakeResponse:
    def __init__(self, status: int, *, headers=None, content: bytes = b"") -> None:
        self.status = status
        self.headers = headers or {}
        self._chunks = [content, b""]
        self.closed = False

    def read(self, _size: int) -> bytes:
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.sock = None
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _target(url: str, hostname: str = "feed.example.test"):
    return external_subscriptions.ValidatedExternalURL(
        url=url,
        hostname=hostname,
        host_header=hostname,
        request_target="/subscription",
        addresses=("203.0.113.80",),
    )


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("198.51.100.10", 54321),
            "server": ("panel.example", 443),
        }
    )


class ExternalSubscriptionParserTests(unittest.TestCase):
    def assert_parse_code(self, document: bytes, expected: str) -> None:
        with self.assertRaises(external_subscriptions.ExternalSubscriptionParseError) as raised:
            external_subscriptions.parse_clash_subscription(document)
        self.assertEqual(expected, raised.exception.code)

    def test_rejects_aliases_and_anchors_before_construction(self) -> None:
        self.assert_parse_code(
            b"proxies:\n  - &base {name: one, type: vmess, server: one.test, port: 443}\n"
            b"  - *base\n",
            "yaml_aliases_not_allowed",
        )

    def test_rejects_duplicate_mapping_keys(self) -> None:
        self.assert_parse_code(
            b"proxies:\n  - name: first\n    name: second\n"
            b"    type: vmess\n    server: one.test\n    port: 443\n",
            "invalid_yaml",
        )

    def test_rejects_deep_yaml_before_safe_load(self) -> None:
        nested = "value"
        for _ in range(external_subscriptions.MAX_YAML_DEPTH + 2):
            nested = f"[{nested}]"
        self.assert_parse_code(
            f"proxies: {nested}\n".encode("utf-8"),
            "yaml_too_deep",
        )

    def test_empty_proxy_list_is_not_a_new_good_snapshot(self) -> None:
        self.assert_parse_code(b"proxies: []\n", "no_usable_nodes")

    def test_upstream_group_references_are_not_imported_as_nodes(self) -> None:
        document = (
            b"proxies:\n"
            b"  - {name: safe, type: vmess, server: safe.test, port: '443'}\n"
            b"  - {name: chained, type: vmess, server: chain.test, port: 443, "
            b"dialer-proxy: upstream}\n"
        )
        parsed = external_subscriptions.parse_clash_subscription(document)
        self.assertEqual(["safe"], [node.name for node in parsed.nodes])
        self.assertEqual(1, parsed.skipped_node_count)
        self.assertEqual(443, parsed.nodes[0].payload["port"])

    def test_node_identity_survives_reordering_distinct_endpoints(self) -> None:
        nodes = [
            {
                "name": "Hong Kong",
                "type": "vmess",
                "server": "first.example.test",
                "port": 443,
            },
            {
                "name": "Hong Kong",
                "type": "vmess",
                "server": "second.example.test",
                "port": 8443,
            },
        ]
        first = external_subscriptions.parse_clash_subscription(
            json.dumps({"proxies": nodes}).encode()
        )
        reordered = external_subscriptions.parse_clash_subscription(
            json.dumps({"proxies": list(reversed(nodes))}).encode()
        )
        self.assertEqual(
            {node.payload["server"]: node.external_key for node in first.nodes},
            {
                node.payload["server"]: node.external_key
                for node in reordered.nodes
            },
        )

    def test_identical_endpoint_occurrences_have_distinct_stable_keys(self) -> None:
        node = {
            "name": "Duplicate",
            "type": "ss",
            "server": "same.example.test",
            "port": 443,
        }
        parsed = external_subscriptions.parse_clash_subscription(
            json.dumps({"proxies": [node, node]}).encode()
        )
        self.assertEqual(2, len({item.external_key for item in parsed.nodes}))
        repeated = external_subscriptions.parse_clash_subscription(
            json.dumps({"proxies": [node, node]}).encode()
        )
        self.assertEqual(
            [item.external_key for item in parsed.nodes],
            [item.external_key for item in repeated.nodes],
        )


class ExternalSubscriptionFetcherTests(unittest.TestCase):
    def test_validated_request_target_preserves_escaped_query_exactly(self) -> None:
        url = (
            "https://feed.example.test/getData/Authorize/synthetic"
            "?burn=abc%2Fdef%2Bghi%3D&mode=clash"
        )
        with patch.object(
            external_subscriptions.socket,
            "getaddrinfo",
            return_value=[
                (
                    external_subscriptions.socket.AF_INET,
                    external_subscriptions.socket.SOCK_STREAM,
                    6,
                    "",
                    ("8.8.8.8", 443),
                )
            ],
        ):
            target = external_subscriptions._validate_public_https_url(url)

        self.assertEqual(url, target.url)
        self.assertEqual(
            "/getData/Authorize/synthetic?burn=abc%2Fdef%2Bghi%3D&mode=clash",
            target.request_target,
        )

    def test_pinned_fetch_200_is_bounded_and_returns_cache_validators(self) -> None:
        connection = _FakeConnection()
        response = _FakeResponse(
            200,
            headers={"ETag": '"synthetic-v1"', "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"},
            content=b"proxies: []\n",
        )
        with (
            patch.object(
                external_subscriptions,
                "_validate_public_https_url",
                return_value=_target(CANARY_URL),
            ),
            patch.object(
                external_subscriptions,
                "_open_pinned_response",
                return_value=(connection, response),
            ) as opened,
        ):
            fetched = external_subscriptions.fetch_clash_subscription(CANARY_URL)

        self.assertEqual(b"proxies: []\n", fetched.content)
        self.assertEqual('"synthetic-v1"', fetched.etag)
        self.assertFalse(fetched.not_modified)
        self.assertTrue(connection.closed)
        self.assertTrue(response.closed)
        opened.assert_called_once()
        request_headers = opened.call_args.kwargs["headers"]
        self.assertEqual("clash.meta", request_headers["User-Agent"])
        self.assertEqual("*/*", request_headers["Accept"])

    def test_pinned_fetch_304_preserves_existing_validators(self) -> None:
        connection = _FakeConnection()
        response = _FakeResponse(304)
        with (
            patch.object(
                external_subscriptions,
                "_validate_public_https_url",
                return_value=_target(CANARY_URL),
            ),
            patch.object(
                external_subscriptions,
                "_open_pinned_response",
                return_value=(connection, response),
            ),
        ):
            fetched = external_subscriptions.fetch_clash_subscription(
                CANARY_URL,
                etag='"old"',
                last_modified="old-date",
            )
        self.assertTrue(fetched.not_modified)
        self.assertIsNone(fetched.content)
        self.assertEqual('"old"', fetched.etag)
        self.assertEqual("old-date", fetched.last_modified)

    def test_each_redirect_is_revalidated_and_re_pinned(self) -> None:
        first = _target(CANARY_URL)
        redirected_url = "https://redirect.example.test/new-feed"
        second = external_subscriptions.ValidatedExternalURL(
            url=redirected_url,
            hostname="redirect.example.test",
            host_header="redirect.example.test",
            request_target="/new-feed",
            addresses=("203.0.113.81",),
        )
        responses = [
            (_FakeConnection(), _FakeResponse(302, headers={"Location": redirected_url})),
            (_FakeConnection(), _FakeResponse(200, content=b"proxies: []\n")),
        ]
        with (
            patch.object(
                external_subscriptions,
                "_validate_public_https_url",
                side_effect=[first, second],
            ) as validate,
            patch.object(
                external_subscriptions,
                "_open_pinned_response",
                side_effect=responses,
            ) as opened,
        ):
            fetched = external_subscriptions.fetch_clash_subscription(CANARY_URL)

        self.assertEqual(b"proxies: []\n", fetched.content)
        self.assertEqual([CANARY_URL, redirected_url], [call.args[0] for call in validate.call_args_list])
        self.assertIs(first, opened.call_args_list[0].args[0])
        self.assertIs(second, opened.call_args_list[1].args[0])

    def test_auth_http_statuses_become_secret_free_diagnostic_codes(self) -> None:
        for status in (401, 403, 404, 410):
            with self.subTest(status=status):
                with (
                    patch.object(
                        external_subscriptions,
                        "_validate_public_https_url",
                        return_value=_target(CANARY_URL),
                    ),
                    patch.object(
                        external_subscriptions,
                        "_open_pinned_response",
                        return_value=(_FakeConnection(), _FakeResponse(status)),
                    ),
                ):
                    with self.assertRaises(
                        external_subscriptions.ExternalSubscriptionFetchError
                    ) as raised:
                        external_subscriptions.fetch_clash_subscription(CANARY_URL)
                self.assertEqual(
                    f"upstream_http_{status}",
                    raised.exception.code,
                )
                self.assertNotIn(CANARY_SECRET, str(raised.exception))

    def test_network_error_without_http_status_never_echoes_socket_message(self) -> None:
        target = _target(CANARY_URL)
        connection = Mock()
        connection.request.side_effect = OSError(f"failed to connect {CANARY_URL}")
        with patch.object(
            external_subscriptions,
            "_PinnedHTTPSConnection",
            return_value=connection,
        ):
            with self.assertRaises(external_subscriptions.ExternalSubscriptionFetchError) as raised:
                external_subscriptions._open_pinned_response(
                    target,
                    headers={},
                    deadline=time.monotonic() + 1,
                )
        self.assertEqual("network_error", raised.exception.code)
        self.assertNotIn(CANARY_SECRET, str(raised.exception))

    def test_scheduler_never_logs_exception_text_containing_write_only_url(self) -> None:
        from app.jobs import external_subscriptions as refresh_job

        db_context = MagicMock()
        db_context.__enter__.return_value = Mock(name="scheduler-db")
        with (
            patch.object(refresh_job, "GetDB", return_value=db_context),
            patch.object(
                refresh_job.external_subscriptions,
                "due_source_ids",
                return_value=[19],
            ),
            patch.object(
                refresh_job.external_subscriptions,
                "refresh_source",
                side_effect=RuntimeError(f"unexpected failure for {CANARY_URL}"),
            ) as refreshed,
            patch.object(refresh_job.secrets, "token_hex", return_value="safe-event-id"),
            patch.object(refresh_job.logger, "error") as logged,
        ):
            refresh_job.refresh_due_external_subscriptions()

        logged.assert_called_once()
        refreshed.assert_called_once_with(
            db_context.__enter__.return_value,
            19,
            scheduled=True,
        )
        rendered_call = repr((logged.call_args.args, logged.call_args.kwargs))
        self.assertNotIn(CANARY_URL, rendered_call)
        self.assertNotIn(CANARY_SECRET, rendered_call)
        self.assertIn("safe-event-id", rendered_call)


class ExternalSubscriptionDatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {"EXTERNAL_SUBSCRIPTION_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY},
        )
        self._env.start()
        self.addCleanup(self._env.stop)

        self._tempdir = tempfile.TemporaryDirectory(prefix="marzban-external-test-")
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
        self.db.add(ExternalSubscriptionBudgetLock(id=1, version=0))
        self.db.commit()

    def create_source(self, name: str = "Synthetic feed") -> ExternalSubscriptionSource:
        return external_subscriptions.create_source(
            self.db,
            name=name,
            group_name=f"{name} group",
            created_by="test-admin",
        )

    def import_nodes(self, source: ExternalSubscriptionSource, *names: str):
        return external_subscriptions.import_snapshot(self.db, source, _snapshot(*names))

    def create_user(self, username: str) -> User:
        user = User(
            username=username,
            status=UserStatus.active,
            used_traffic=0,
            data_limit=None,
            data_limit_reset_strategy=UserDataLimitResetStrategy.no_reset,
            expire=None,
            created_at=datetime.utcnow(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def attach_plan(self, plan: SubscriptionPlan, username: str) -> User:
        user = self.create_user(username)
        now = datetime.utcnow()
        account = PortalAccount(
            username=username,
            hashed_password="not-a-real-password-hash",
            user_id=user.id,
        )
        account.subscription = PortalSubscription(
            plan_id=plan.id,
            plan_name=plan.name,
            price_paid_minor=0,
            currency="CNY",
            duration_days=30,
            data_limit=0,
            inbound_tags=[],
            starts_at=now,
            expires_at=now + timedelta(days=30),
            purchased_at=now,
        )
        self.db.add(account)
        self.db.commit()
        return user


class ExternalSubscriptionEncryptionTests(ExternalSubscriptionDatabaseTestCase):
    def test_external_key_is_independent_from_mgma_pepper(self) -> None:
        with patch.dict(os.environ, {"MGMA_TOKEN_PEPPER": "x" * 64}):
            encrypted = external_subscriptions.encrypt_url(CANARY_URL)
        with patch.dict(os.environ, {"MGMA_TOKEN_PEPPER": "y" * 64}):
            self.assertEqual(CANARY_URL, external_subscriptions.decrypt_url(encrypted))

        with patch.dict(
            os.environ,
            {
                "EXTERNAL_SUBSCRIPTION_ENCRYPTION_KEY": "",
                "MGMA_TOKEN_PEPPER": "z" * 64,
            },
        ):
            with self.assertRaises(
                external_subscriptions.ExternalSubscriptionConfigurationError
            ) as raised:
                external_subscriptions.encrypt_url(CANARY_URL)
        self.assertEqual("encryption_key_unavailable", raised.exception.code)

    def test_write_only_url_and_payload_are_encrypted_and_absent_from_responses(self) -> None:
        with patch.object(
            external_subscriptions,
            "_validate_public_https_url",
            return_value=_target(CANARY_URL),
        ):
            source = external_subscriptions.create_source(
                self.db,
                name="Write-only source",
                group_name="Write-only group",
                created_by="test-admin",
                url=CANARY_URL,
            )
        external_subscriptions.import_snapshot(
            self.db,
            source,
            _snapshot("Encrypted node", secret=CANARY_SECRET),
        )
        node = self.db.query(ExternalSubscriptionNode).filter_by(source_id=source.id).one()

        source_json = ExternalSubscriptionSourceResponse.model_validate(source).model_dump()
        node_json = ExternalSubscriptionNodeResponse.model_validate(node).model_dump()
        serialized = json.dumps(
            {"source": source_json, "node": node_json},
            default=str,
            sort_keys=True,
        )
        self.assertNotIn("url", source_json)
        self.assertNotIn("url_ciphertext", source_json)
        self.assertNotIn("payload", node_json)
        self.assertNotIn(CANARY_SECRET, serialized)
        self.assertNotIn(CANARY_URL, serialized)
        self.assertEqual(CANARY_URL, external_subscriptions.decrypt_url(source.url_ciphertext))
        self.assertEqual(
            f"{CANARY_SECRET}-0",
            external_subscriptions.decrypt_proxy_payload(node.payload_ciphertext)["uuid"],
        )

        self.db.close()
        self.engine.dispose()
        with open(self.database_path, "rb") as database_file:
            raw_database = database_file.read()
        self.assertNotIn(CANARY_URL.encode("utf-8"), raw_database)
        self.assertNotIn(CANARY_SECRET.encode("utf-8"), raw_database)


class ExternalSubscriptionLifecycleTests(ExternalSubscriptionDatabaseTestCase):
    def test_global_budget_lock_serializes_snapshot_and_plan_mutations(self) -> None:
        external_subscriptions.lock_external_budget_for_update(self.db)
        second = self.Session()
        self.addCleanup(second.close)
        second.execute(text("PRAGMA busy_timeout = 50"))
        with self.assertRaises(OperationalError):
            external_subscriptions.lock_external_budget_for_update(second)
        second.rollback()
        self.db.rollback()
        external_subscriptions.lock_external_budget_for_update(second)
        second.rollback()

    def test_source_write_lock_serializes_competing_mutations(self) -> None:
        source = self.create_source()
        source_id = source.id
        external_subscriptions.lock_external_sources_for_update(
            self.db,
            [source_id],
        )
        second = self.Session()
        self.addCleanup(second.close)
        second.execute(text("PRAGMA busy_timeout = 50"))
        with self.assertRaises(OperationalError):
            external_subscriptions.lock_external_sources_for_update(
                second,
                [source_id],
            )
        second.rollback()
        self.db.rollback()
        self.assertEqual(
            source_id,
            external_subscriptions.lock_external_sources_for_update(
                second,
                [source_id],
            )[source_id].id,
        )
        second.rollback()

    def test_plan_write_lock_serializes_cross_source_budget_decisions(self) -> None:
        source = self.create_source()
        self.import_nodes(source, "Existing")
        plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Shared budget lock",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source.id, mode="all")
                ],
            ),
        )
        external_subscriptions.lock_subscription_plans_for_update(
            self.db,
            [plan.id],
        )
        second = self.Session()
        self.addCleanup(second.close)
        second.execute(text("PRAGMA busy_timeout = 50"))
        with self.assertRaises(OperationalError):
            external_subscriptions.lock_subscription_plans_for_update(
                second,
                [plan.id],
            )
        second.rollback()
        self.db.rollback()
        external_subscriptions.lock_subscription_plans_for_update(
            second,
            [plan.id],
        )
        second.rollback()

    def test_missing_source_cannot_leave_a_stale_plan_reference(self) -> None:
        with self.assertRaises(commerce.PlanConfigurationError) as raised:
            commerce.create_plan(
                self.db,
                SubscriptionPlanCreate(
                    name="Missing source plan",
                    price_minor=0,
                    duration_days=30,
                    data_limit=0,
                    inbound_tags=[],
                    external_selections=[
                        ExternalSelectionInput(source_id=999999, mode="all")
                    ],
                ),
            )
        self.assertIn("do not exist", str(raised.exception))
        self.db.rollback()
        self.assertIsNone(
            self.db.query(SubscriptionPlan)
            .filter_by(name="Missing source plan")
            .first()
        )

    def test_stale_plan_object_is_reloaded_after_budget_mutex(self) -> None:
        source_a = self.create_source("Stale source A")
        source_b = self.create_source("Stale source B")
        source_c = self.create_source("Stale source C")
        self.import_nodes(source_a, "A")
        self.import_nodes(source_b, "B")
        self.import_nodes(source_c, "C")
        plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Stale plan reload",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source_a.id, mode="all")
                ],
            ),
        )
        first = self.Session()
        second = self.Session()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first_plan = first.get(SubscriptionPlan, plan.id)
        second_plan = second.get(SubscriptionPlan, plan.id)

        commerce.update_plan(
            first,
            first_plan,
            SubscriptionPlanUpdate(
                external_selections=[
                    ExternalSelectionInput(source_id=source_b.id, mode="all")
                ]
            ),
        )
        commerce.update_plan(
            second,
            second_plan,
            SubscriptionPlanUpdate(
                external_selections=[
                    ExternalSelectionInput(source_id=source_c.id, mode="all")
                ]
            ),
        )

        self.db.expire_all()
        self.assertEqual(
            [source_c.id],
            [
                selection.source_id
                for selection in self.db.query(SubscriptionPlanExternalSelection)
                .filter_by(plan_id=plan.id)
                .all()
            ],
        )

    def test_plan_creation_rejects_projected_node_and_byte_overlays(self) -> None:
        source = self.create_source()
        self.import_nodes(source, "First", "Second")
        values = SubscriptionPlanCreate(
            name="Over budget",
            price_minor=0,
            duration_days=30,
            data_limit=0,
            inbound_tags=[],
            external_selections=[
                ExternalSelectionInput(source_id=source.id, mode="all")
            ],
        )
        with (
            patch.object(external_subscriptions, "MAX_OVERLAY_NODES", 1),
            self.assertRaises(commerce.PlanConfigurationError) as node_error,
        ):
            commerce.create_plan(self.db, values)
        self.assertEqual("overlay_limit_exceeded", str(node_error.exception))
        self.db.rollback()

        with (
            patch.object(external_subscriptions, "MAX_OVERLAY_DECRYPTED_BYTES", 1),
            self.assertRaises(commerce.PlanConfigurationError) as byte_error,
        ):
            commerce.create_plan(self.db, values)
        self.assertEqual("overlay_limit_exceeded", str(byte_error.exception))
        self.db.rollback()

    def test_over_budget_refresh_keeps_last_known_good_snapshot(self) -> None:
        source = self.create_source()
        self.import_nodes(source, "Last known good")
        commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Bounded refresh plan",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source.id, mode="all")
                ],
            ),
        )

        with (
            patch.object(external_subscriptions, "MAX_OVERLAY_NODES", 1),
            self.assertRaises(
                external_subscriptions.ExternalSubscriptionConfigurationError
            ) as raised,
        ):
            external_subscriptions.import_snapshot(
                self.db,
                source,
                _snapshot("Replacement one", "Replacement two"),
            )
        self.assertEqual("overlay_limit_exceeded", raised.exception.code)
        self.db.expire_all()
        self.assertEqual(
            ["Last known good"],
            [
                node.name
                for node in self.db.query(ExternalSubscriptionNode)
                .filter_by(source_id=source.id)
                .all()
            ],
        )

    def test_second_source_refresh_observes_first_source_committed_budget(self) -> None:
        source_a = self.create_source("Source A")
        source_b = self.create_source("Source B")
        self.import_nodes(source_a, "A old")
        self.import_nodes(source_b, "B old")
        commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Cross-source budget",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source_a.id, mode="all"),
                    ExternalSelectionInput(source_id=source_b.id, mode="all"),
                ],
            ),
        )

        with patch.object(external_subscriptions, "MAX_OVERLAY_NODES", 3):
            external_subscriptions.import_snapshot(
                self.db,
                source_a,
                _snapshot("A new one", "A new two"),
            )
            with self.assertRaises(
                external_subscriptions.ExternalSubscriptionConfigurationError
            ) as raised:
                external_subscriptions.import_snapshot(
                    self.db,
                    source_b,
                    _snapshot("B new one", "B new two"),
                )
        self.assertEqual("overlay_limit_exceeded", raised.exception.code)
        self.db.expire_all()
        self.assertEqual(
            ["A new one", "A new two"],
            [
                node.name
                for node in self.db.query(ExternalSubscriptionNode)
                .filter_by(source_id=source_a.id)
                .order_by(ExternalSubscriptionNode.position.asc())
                .all()
            ],
        )
        self.assertEqual(
            ["B old"],
            [
                node.name
                for node in self.db.query(ExternalSubscriptionNode)
                .filter_by(source_id=source_b.id)
                .all()
            ],
        )

    def test_concurrent_cross_source_refreshes_share_the_budget_mutex(self) -> None:
        source_a = self.create_source("Concurrent source A")
        source_b = self.create_source("Concurrent source B")
        self.import_nodes(source_a, "A old")
        self.import_nodes(source_b, "B old")
        commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Concurrent cross-source budget",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source_a.id, mode="all"),
                    ExternalSelectionInput(source_id=source_b.id, mode="all"),
                ],
            ),
        )

        claimed_a, token_a = external_subscriptions._claim_snapshot_lease(
            self.db,
            source_a.id,
            now=datetime.utcnow(),
        )
        claimed_b, token_b = external_subscriptions._claim_snapshot_lease(
            self.db,
            source_b.id,
            now=datetime.utcnow(),
        )
        candidate_a = external_subscriptions.parse_clash_subscription(
            _snapshot("A new one", "A new two")
        )
        candidate_b = external_subscriptions.parse_clash_subscription(
            _snapshot("B new one", "B new two")
        )
        first_in_budget_check = threading.Event()
        release_first = threading.Event()
        second_attempted_mutex = threading.Event()
        second_in_budget_check = threading.Event()
        outcomes: list[tuple[int, str]] = []
        original_lock = external_subscriptions.lock_external_budget_for_update
        original_validate = external_subscriptions._validate_snapshot_plan_budgets

        def coordinated_lock(db):
            if threading.current_thread().name == "budget-source-b":
                second_attempted_mutex.set()
            return original_lock(db)

        def coordinated_validate(db, source_id, snapshot):
            if source_id == source_a.id:
                first_in_budget_check.set()
                if not release_first.wait(timeout=5):
                    raise RuntimeError("test synchronization timeout")
            elif source_id == source_b.id:
                second_in_budget_check.set()
            return original_validate(db, source_id, snapshot)

        def publish(source_id: int, lease_token: str, snapshot) -> None:
            session = self.Session()
            try:
                source = session.get(ExternalSubscriptionSource, source_id)
                external_subscriptions._apply_snapshot(
                    session,
                    source,
                    snapshot,
                    now=datetime.utcnow(),
                    remote=False,
                    lease_token=lease_token,
                )
                outcomes.append((source_id, "ok"))
            except external_subscriptions.ExternalSubscriptionError as exc:
                outcomes.append((source_id, exc.code))
            finally:
                external_subscriptions._release_refresh_lease(
                    session,
                    source_id,
                    lease_token,
                )
                session.close()

        with (
            patch.object(external_subscriptions, "MAX_OVERLAY_NODES", 3),
            patch.object(
                external_subscriptions,
                "lock_external_budget_for_update",
                side_effect=coordinated_lock,
            ),
            patch.object(
                external_subscriptions,
                "_validate_snapshot_plan_budgets",
                side_effect=coordinated_validate,
            ),
        ):
            first = threading.Thread(
                target=publish,
                args=(claimed_a.id, token_a, candidate_a),
                name="budget-source-a",
            )
            second = threading.Thread(
                target=publish,
                args=(claimed_b.id, token_b, candidate_b),
                name="budget-source-b",
            )
            first.start()
            self.assertTrue(first_in_budget_check.wait(timeout=5))
            second.start()
            self.assertTrue(second_attempted_mutex.wait(timeout=5))
            self.assertFalse(second_in_budget_check.is_set())
            release_first.set()
            first.join(timeout=5)
            second.join(timeout=5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertTrue(second_in_budget_check.is_set())

        self.assertCountEqual(
            [
                (source_a.id, "ok"),
                (source_b.id, "overlay_limit_exceeded"),
            ],
            outcomes,
        )
        self.db.expire_all()
        self.assertEqual(
            ["B old"],
            [
                node.name
                for node in self.db.query(ExternalSubscriptionNode)
                .filter_by(source_id=source_b.id)
                .all()
            ],
        )

    def test_failed_refresh_keeps_last_known_good_nodes(self) -> None:
        source = self.create_source()
        self.import_nodes(source, "Last known good")
        node = self.db.query(ExternalSubscriptionNode).filter_by(source_id=source.id).one()
        old_ciphertext = node.payload_ciphertext
        old_success = source.last_success_at
        source.url_ciphertext = external_subscriptions.encrypt_url(CANARY_URL)
        source.url_revision = 1
        source.next_refresh_at = datetime.utcnow()
        self.db.commit()

        with patch.object(
            external_subscriptions,
            "fetch_clash_subscription",
            side_effect=external_subscriptions.ExternalSubscriptionFetchError(
                "upstream_http_403"
            ),
        ):
            with self.assertRaises(external_subscriptions.ExternalSubscriptionFetchError):
                external_subscriptions.refresh_source(self.db, source.id)
        self.db.expire_all()
        source = self.db.get(ExternalSubscriptionSource, source.id)
        node = self.db.query(ExternalSubscriptionNode).filter_by(source_id=source.id).one()
        self.assertEqual("auth_required", source.status)
        self.assertEqual("upstream_http_403", source.last_error_code)
        self.assertIsNone(source.next_refresh_at)
        self.assertEqual(old_success, source.last_success_at)
        self.assertEqual(old_ciphertext, node.payload_ciphertext)
        self.assertTrue(node.is_active)

        with patch.object(
            external_subscriptions,
            "fetch_clash_subscription",
            return_value=external_subscriptions.FetchedExternalPayload(
                content=b"proxies: []\n",
                etag=None,
                last_modified=None,
            ),
        ):
            with self.assertRaises(external_subscriptions.ExternalSubscriptionParseError):
                external_subscriptions.refresh_source(self.db, source.id)
        self.db.expire_all()
        source = self.db.get(ExternalSubscriptionSource, source.id)
        node = self.db.query(ExternalSubscriptionNode).filter_by(source_id=source.id).one()
        self.assertEqual("error", source.status)
        self.assertEqual("no_usable_nodes", source.last_error_code)
        self.assertEqual(old_ciphertext, node.payload_ciphertext)

    def test_manual_refresh_updates_disabled_source_without_scheduling(self) -> None:
        source = self.create_source("Manual refresh source")
        source.enabled = False
        source.status = "disabled"
        source.url_ciphertext = external_subscriptions.encrypt_url(CANARY_URL)
        source.url_revision = 1
        source.next_refresh_at = None
        self.db.commit()
        attempt_at = datetime.utcnow()

        with patch.object(
            external_subscriptions,
            "fetch_clash_subscription",
            return_value=external_subscriptions.FetchedExternalPayload(
                content=_snapshot("Manually refreshed node"),
                etag='"manual-v1"',
                last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
            ),
        ) as fetched:
            refreshed = external_subscriptions.refresh_source(
                self.db,
                source.id,
                now=attempt_at,
            )

        fetched.assert_called_once_with(
            CANARY_URL,
            etag=None,
            last_modified=None,
        )
        self.assertFalse(refreshed.enabled)
        self.assertEqual("disabled", refreshed.status)
        self.assertIsNone(refreshed.next_refresh_at)
        self.assertEqual(attempt_at, refreshed.last_success_at)
        self.assertEqual(1, refreshed.node_count)
        nodes = (
            self.db.query(ExternalSubscriptionNode)
            .filter_by(source_id=source.id)
            .all()
        )
        self.assertEqual(["Manually refreshed node"], [node.name for node in nodes])

    def test_scheduled_refresh_skips_disabled_source_without_fetching(self) -> None:
        source = self.create_source("Disabled scheduled source")
        source.enabled = False
        source.status = "disabled"
        source.url_ciphertext = external_subscriptions.encrypt_url(CANARY_URL)
        source.url_revision = 1
        source.next_refresh_at = None
        self.db.commit()

        with patch.object(
            external_subscriptions,
            "fetch_clash_subscription",
        ) as fetched:
            refreshed = external_subscriptions.refresh_source(
                self.db,
                source.id,
                scheduled=True,
            )

        fetched.assert_not_called()
        self.assertEqual(source.id, refreshed.id)
        self.assertFalse(refreshed.enabled)
        self.assertEqual("disabled", refreshed.status)
        self.assertIsNone(refreshed.next_refresh_at)
        self.assertIsNone(refreshed.refresh_lease_token)

    def test_disabling_schedule_supersedes_generation_claimed_while_enabled(self) -> None:
        source = self.create_source("Disable in-flight source")
        source.url_ciphertext = external_subscriptions.encrypt_url(CANARY_URL)
        source.url_revision = 1
        self.db.commit()
        claimed, lease_token = external_subscriptions._claim_refresh_lease(
            self.db,
            source.id,
            now=datetime.utcnow(),
            require_enabled=False,
        )

        disabled = external_subscriptions.update_source(
            self.db,
            claimed,
            enabled=False,
        )

        self.assertEqual(2, disabled.url_revision)
        self.assertIsNone(disabled.refresh_lease_token)
        self.assertIsNone(disabled.refresh_lease_until)
        self.assertEqual("disabled", disabled.status)
        self.assertIsNone(disabled.next_refresh_at)
        with self.assertRaises(
            external_subscriptions.ExternalSubscriptionConfigurationError
        ) as raised:
            external_subscriptions._apply_snapshot(
                self.db,
                disabled,
                external_subscriptions.parse_clash_subscription(
                    _snapshot("Stale generation")
                ),
                now=datetime.utcnow(),
                remote=True,
                lease_token=lease_token,
            )
        self.assertEqual("refresh_superseded", raised.exception.code)

    def test_refresh_lease_allows_only_one_database_session_to_claim(self) -> None:
        source = self.create_source()
        source.url_ciphertext = external_subscriptions.encrypt_url(CANARY_URL)
        source.next_refresh_at = datetime.utcnow()
        self.db.commit()
        second = self.Session()
        self.addCleanup(second.close)
        now = datetime.utcnow()

        _claimed, first_token = external_subscriptions._claim_refresh_lease(
            self.db,
            source.id,
            now=now,
            require_enabled=True,
        )
        with self.assertRaises(
            external_subscriptions.ExternalSubscriptionConfigurationError
        ) as raised:
            external_subscriptions._claim_refresh_lease(
                second,
                source.id,
                now=now,
                require_enabled=True,
            )
        self.assertEqual("refresh_in_progress", raised.exception.code)
        self.assertNotIn(
            source.id,
            external_subscriptions.due_source_ids(second, now=now),
        )

        self.db.query(ExternalSubscriptionSource).filter_by(id=source.id).update(
            {
                ExternalSubscriptionSource.refresh_lease_until: now - timedelta(seconds=1),
                ExternalSubscriptionSource.refresh_lease_token: first_token,
            },
            synchronize_session=False,
        )
        self.db.commit()
        second.expire_all()
        claimed, second_token = external_subscriptions._claim_refresh_lease(
            second,
            source.id,
            now=now,
            require_enabled=True,
        )
        self.assertEqual(source.id, claimed.id)
        self.assertNotEqual(first_token, second_token)

    def test_new_manual_snapshot_generation_supersedes_stale_writer(self) -> None:
        source = self.create_source()
        first_source, first_token = external_subscriptions._claim_snapshot_lease(
            self.db,
            source.id,
            now=datetime.utcnow(),
        )
        current_source, current_token = external_subscriptions._claim_snapshot_lease(
            self.db,
            source.id,
            now=datetime.utcnow(),
        )

        with self.assertRaises(
            external_subscriptions.ExternalSubscriptionConfigurationError
        ) as raised:
            external_subscriptions._apply_snapshot(
                self.db,
                first_source,
                external_subscriptions.parse_clash_subscription(_snapshot("Stale")),
                now=datetime.utcnow(),
                remote=False,
                lease_token=first_token,
            )
        self.assertEqual("refresh_superseded", raised.exception.code)

        external_subscriptions._apply_snapshot(
            self.db,
            current_source,
            external_subscriptions.parse_clash_subscription(_snapshot("Current")),
            now=datetime.utcnow(),
            remote=False,
            lease_token=current_token,
        )
        nodes = self.db.query(ExternalSubscriptionNode).filter_by(
            source_id=source.id
        ).all()
        self.assertEqual(["Current"], [node.name for node in nodes])

    def test_plan_all_selected_cross_source_and_inactive_node_retention(self) -> None:
        first = self.create_source("First source")
        second = self.create_source("Second source")
        self.import_nodes(first, "Alpha", "Beta", "Unselected stale")
        self.import_nodes(second, "Other source node")
        first_nodes = {
            node.name: node
            for node in self.db.query(ExternalSubscriptionNode)
            .filter_by(source_id=first.id)
            .all()
        }
        beta_node_id = first_nodes["Beta"].id
        unselected_stale_node_id = first_nodes["Unselected stale"].id
        other_node = (
            self.db.query(ExternalSubscriptionNode)
            .filter_by(source_id=second.id)
            .one()
        )

        all_plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="All external nodes",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=first.id, mode="all")
                ],
            ),
        )
        selected_plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Selected external node",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(
                        source_id=first.id,
                        mode="selected",
                        node_ids=[beta_node_id],
                    )
                ],
            ),
        )
        with self.assertRaises(commerce.PlanConfigurationError):
            commerce.create_plan(
                self.db,
                SubscriptionPlanCreate(
                    name="Cross-source selection",
                    price_minor=0,
                    duration_days=30,
                    data_limit=0,
                    inbound_tags=[],
                    external_selections=[
                        ExternalSelectionInput(
                            source_id=first.id,
                            mode="selected",
                            node_ids=[other_node.id],
                        )
                    ],
                ),
            )

        all_user = self.attach_plan(all_plan, "external-all-user")
        selected_user = self.attach_plan(selected_plan, "external-selected-user")
        all_overlay = external_subscriptions.load_external_overlays_for_user(
            self.db, all_user.id
        )
        selected_overlay = external_subscriptions.load_external_overlays_for_user(
            self.db, selected_user.id
        )
        self.assertEqual(
            ["Alpha", "Beta", "Unselected stale"],
            [node["name"] for node in all_overlay[0].nodes],
        )
        self.assertEqual(["Beta"], [node["name"] for node in selected_overlay[0].nodes])

        external_subscriptions.import_snapshot(self.db, first, _snapshot("Alpha"))
        self.db.expire_all()
        retained = self.db.get(ExternalSubscriptionNode, beta_node_id)
        removed = self.db.get(
            ExternalSubscriptionNode,
            unselected_stale_node_id,
        )
        self.assertIsNotNone(retained)
        self.assertFalse(retained.is_active)
        self.assertIsNone(removed)
        self.assertEqual(
            ["Alpha"],
            [
                node["name"]
                for node in external_subscriptions.load_external_overlays_for_user(
                    self.db, all_user.id
                )[0].nodes
            ],
        )
        self.assertEqual(
            [],
            external_subscriptions.load_external_overlays_for_user(
                self.db, selected_user.id
            ),
        )

    def test_disabled_source_keeps_all_and_selected_last_known_good_overlays(self) -> None:
        source = self.create_source("Disabled overlay source")
        self.import_nodes(source, "LKG alpha", "LKG beta")
        nodes = {
            node.name: node
            for node in self.db.query(ExternalSubscriptionNode)
            .filter_by(source_id=source.id)
            .all()
        }
        all_plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Disabled all overlay",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source.id, mode="all")
                ],
            ),
        )
        selected_plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="Disabled selected overlay",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(
                        source_id=source.id,
                        mode="selected",
                        node_ids=[nodes["LKG beta"].id],
                    )
                ],
            ),
        )
        all_user = self.attach_plan(all_plan, "disabled-all-user")
        selected_user = self.attach_plan(selected_plan, "disabled-selected-user")

        source.enabled = False
        source.status = "disabled"
        source.next_refresh_at = None
        self.db.commit()
        self.db.expire_all()

        all_overlay = external_subscriptions.load_external_overlays_for_user(
            self.db,
            all_user.id,
        )
        selected_overlay = external_subscriptions.load_external_overlays_for_user(
            self.db,
            selected_user.id,
        )
        self.assertEqual(
            ["LKG alpha", "LKG beta"],
            [node["name"] for node in all_overlay[0].nodes],
        )
        self.assertEqual(
            ["LKG beta"],
            [node["name"] for node in selected_overlay[0].nodes],
        )

    def test_source_in_use_cannot_be_deleted(self) -> None:
        source = self.create_source()
        self.import_nodes(source, "In-use node")
        plan = commerce.create_plan(
            self.db,
            SubscriptionPlanCreate(
                name="References source",
                price_minor=0,
                duration_days=30,
                data_limit=0,
                inbound_tags=[],
                external_selections=[
                    ExternalSelectionInput(source_id=source.id, mode="all")
                ],
            ),
        )
        self.assertIsNotNone(plan.id)
        self.db.expire_all()
        with self.assertRaises(HTTPException) as raised:
            commerce_router.admin_delete_external_subscription(
                source_id=source.id,
                db=self.db,
                _admin=AdminSchema(username="root", is_sudo=True),
            )
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("source_in_use", raised.exception.detail)
        self.assertIsNotNone(self.db.get(ExternalSubscriptionSource, source.id))


class ExternalSubscriptionRouteTests(unittest.TestCase):
    """Both stable and compatibility subscription routes use the same overlay."""

    def setUp(self) -> None:
        self.db = Mock(name="subscription-db")
        self.dbuser = SimpleNamespace(id=73)
        self.user = SimpleNamespace(
            username="synthetic-user",
            used_traffic=0,
            data_limit=1024,
            expire=0,
        )
        self.source = external_subscriptions.ExternalOverlaySource(
            source_id=8,
            group_name="Synthetic source group",
            nodes=(
                {
                    "name": "Synthetic node",
                    "type": "vmess",
                    "server": "node.example.test",
                    "port": 443,
                    "uuid": "synthetic-uuid",
                },
            ),
        )
        self.expected_overlay = {
            "sources": [
                {
                    "id": 8,
                    "group_name": "Synthetic source group",
                    "nodes": list(self.source.nodes),
                }
            ]
        }

    def _assert_rendered(self, renderer: Mock, expected_format: str) -> None:
        self.assertEqual(expected_format, renderer.call_args.kwargs["config_format"])
        self.assertEqual(
            self.expected_overlay,
            renderer.call_args.kwargs["clash_overlay"],
        )

    def test_stable_subscription_auto_and_explicit_clash_matrix(self) -> None:
        cases = (
            (None, "Clash-Verge/2.3", "clash-meta"),
            (None, "Clash/1.18", "clash"),
            ("clash-meta", "irrelevant", "clash-meta"),
            ("clash", "irrelevant", "clash"),
        )
        for client_type, user_agent, expected_format in cases:
            with self.subTest(client_type=client_type, user_agent=user_agent):
                request = _request("/sub/stable-token/")
                request.state.subscription_user_snapshot = self.user
                with (
                    patch.object(subscription_router.crud, "update_user_sub"),
                    patch.object(
                        subscription_router,
                        "load_external_overlays_for_user",
                        return_value=[self.source],
                    ) as load_overlay,
                    patch.object(
                        subscription_router,
                        "generate_subscription",
                        return_value="rendered",
                    ) as renderer,
                ):
                    if client_type is None:
                        response = subscription_router.user_subscription(
                            request=request,
                            db=self.db,
                            dbuser=self.dbuser,
                            user_agent=user_agent,
                        )
                    else:
                        response = subscription_router.user_subscription_with_client_type(
                            request=request,
                            dbuser=self.dbuser,
                            client_type=client_type,
                            db=self.db,
                            user_agent=user_agent,
                        )
                self.assertEqual(b"rendered", response.body)
                load_overlay.assert_called_once_with(self.db, self.dbuser.id)
                self._assert_rendered(renderer, expected_format)

    def test_legacy_mgma_auto_and_explicit_clash_matrix(self) -> None:
        cases = (
            (None, "Mihomo/1.19", "clash-meta"),
            (None, "Stash/2.6", "clash"),
            ("clash-meta", "irrelevant", "clash-meta"),
            ("clash", "irrelevant", "clash"),
        )
        for client_type, user_agent, expected_format in cases:
            with self.subTest(client_type=client_type, user_agent=user_agent):
                request = _request("/sub/mgma")
                with (
                    patch.object(
                        mgma_router,
                        "_validated_mgma_user",
                        return_value=self.dbuser,
                    ),
                    patch.object(
                        mgma_router.UserResponse,
                        "model_validate",
                        return_value=self.user,
                    ),
                    patch.object(
                        mgma_router,
                        "token_generation_matches",
                        return_value=True,
                    ),
                    patch.object(mgma_router.crud, "update_user_sub"),
                    patch.object(
                        subscription_router,
                        "load_external_overlays_for_user",
                        return_value=[self.source],
                    ) as load_overlay,
                    patch.object(
                        subscription_router,
                        "generate_subscription",
                        return_value="rendered",
                    ) as renderer,
                ):
                    if client_type is None:
                        response = mgma_router.mgma_subscription(
                            request=request,
                            token="synthetic-query-token",
                            user_agent=user_agent,
                            db=self.db,
                        )
                    else:
                        response = mgma_router.mgma_subscription_with_client_type(
                            request=request,
                            token="synthetic-query-token",
                            client_type=client_type,
                            user_agent=user_agent,
                            db=self.db,
                        )
                self.assertEqual(b"rendered", response.body)
                load_overlay.assert_called_once_with(self.db, self.dbuser.id)
                self._assert_rendered(renderer, expected_format)
                self.assertEqual(
                    "private, no-store, max-age=0",
                    response.headers["cache-control"],
                )

    def test_non_clash_output_does_not_load_or_decrypt_external_nodes(self) -> None:
        with (
            patch.object(
                subscription_router,
                "load_external_overlays_for_user",
            ) as load_overlay,
            patch.object(
                subscription_router,
                "generate_subscription",
                return_value="rendered",
            ) as renderer,
        ):
            response = subscription_router.build_subscription_response(
                user=self.user,
                client_type="v2ray",
                db=self.db,
                user_id=self.dbuser.id,
            )
        self.assertEqual(b"rendered", response.body)
        load_overlay.assert_not_called()
        self.assertIsNone(renderer.call_args.kwargs["clash_overlay"])

    def test_overlay_failure_is_a_generic_503_without_secret_details(self) -> None:
        sensitive_code = f"encrypted_data_unavailable:{CANARY_URL}"
        with (
            patch.object(
                subscription_router,
                "load_external_overlays_for_user",
                side_effect=external_subscriptions.ExternalSubscriptionConfigurationError(
                    sensitive_code
                ),
            ),
            patch.object(subscription_router, "generate_subscription") as renderer,
        ):
            with self.assertRaises(HTTPException) as raised:
                subscription_router.build_subscription_response(
                    user=self.user,
                    user_agent="Clash-Verge/2.3",
                    db=self.db,
                    user_id=self.dbuser.id,
                )
        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual(
            "Subscription temporarily unavailable",
            raised.exception.detail,
        )
        self.assertNotIn(CANARY_SECRET, str(raised.exception))
        self.assertNotIn(CANARY_SECRET, repr(raised.exception))
        renderer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
