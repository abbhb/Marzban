"""Private feed ownership, HTTP permissions, quotas and final subscription delivery."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from sqlalchemy.exc import IntegrityError

from app import app
from app.db import get_db, crud
from app.db.models import ExternalSubscriptionSource, PortalAccount, SubscriptionPlan, Proxy
from app.models.admin import AdminCreate
from app.models.commerce import ExternalSelectionInput, SubscriptionPlanCreate, SubscriptionPlanUpdate
from app.models.user import UserResponse
from app.models.proxy import ProxyTypes, VLESSSettings
from app.routers import commerce as routes
from app.routers.subscription import build_subscription_response
from app.services import commerce, external_subscriptions as service
from app.utils.jwt import create_admin_token, create_portal_token
from tests.test_external_subscriptions import ExternalSubscriptionDatabaseTestCase, _snapshot, CANARY_URL, CANARY_SECRET


class PrivateExternalTests(ExternalSubscriptionDatabaseTestCase):
    def setUp(self):
        super().setUp()
        secret_patch = patch("app.utils.jwt.get_secret_key", return_value="private-http-test-secret")
        secret_patch.start()
        self.addCleanup(secret_patch.stop)
        inbound_patch = patch.multiple(commerce.xray.config, inbounds_by_tag={"TEST": {"tag": "TEST", "protocol": "vless"}}, inbounds_by_protocol={})
        inbound_patch.start()
        self.addCleanup(inbound_patch.stop)
        plan = commerce.create_plan(self.db, SubscriptionPlanCreate(
            name="Shared plan", price_minor=0, duration_days=30, data_limit=0,
            inbound_tags=["TEST"], external_selections=[]))
        self.alice_user = self.attach_plan(plan, "alice-private")
        self.bob_user = self.attach_plan(plan, "bob-private")
        for user in (self.alice_user, self.bob_user):
            user.proxies.append(Proxy(type=ProxyTypes.VLESS, settings=VLESSSettings().dict(no_obj=True)))
        self.db.commit()
        self.alice = self.db.query(PortalAccount).filter_by(user_id=self.alice_user.id).one()
        self.bob = self.db.query(PortalAccount).filter_by(user_id=self.bob_user.id).one()
        self.admin = crud.create_admin(self.db, AdminCreate(username="private-root", password="test-password", is_sudo=True))
        self.limited_admin = crud.create_admin(self.db, AdminCreate(username="private-limited", password="test-password", is_sudo=False))
        app.dependency_overrides[get_db] = self.review_db
        self.addCleanup(app.dependency_overrides.pop, get_db)
        routes.PORTAL_RATE_LIMITER._events.clear()

    def review_db(self):
        with self.Session() as db:
            yield db

    def private_source(self, account=None, name="My feed"):
        account = account or self.alice
        return service.create_source(self.db, name=name, group_name=name,
                                     created_by=account.username, owner_account_id=account.id)

    def request(self, method, path, account=None, *, payload=None, snapshot=None, token=None):
        if token is None and account is not None:
            token = create_portal_token(account.id, account.username)
        body = json.dumps(payload).encode() if payload is not None else b""
        headers = [(b"host", b"testserver")]
        if token:
            headers.append((b"authorization", f"Bearer {token}".encode()))
        if snapshot is not None:
            boundary = "private-test-boundary"
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="nodes.yaml"\r\nContent-Type: text/yaml\r\n\r\n'.encode()
                    + snapshot + f'\r\n--{boundary}--\r\n'.encode())
            headers.append((b"content-type", f"multipart/form-data; boundary={boundary}".encode()))
        elif payload is not None:
            headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(body)).encode()))
        start, result = {}, bytearray()
        received = False
        response_finished = asyncio.Event()
        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await response_finished.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                result.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    response_finished.set()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": method, "scheme": "http", "path": path,
                 "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": headers,
                 "client": ("198.51.100.77", 50000), "server": ("testserver", 80)}
        asyncio.run(app(scope, receive, send))
        return SimpleNamespace(status=start["status"], body=bytes(result),
                               headers={k.decode(): v.decode() for k, v in start["headers"]},
                               json=lambda: json.loads(result) if result else None)

    def test_creation_forces_authenticated_owner_and_list_isolation(self):
        shared = self.create_source("Shared")
        response = self.request("POST", "/api/portal/external-subscriptions", self.alice,
                                payload={"name": "My feed", "owner_account_id": self.bob.id})
        self.assertEqual(201, response.status, response.body)
        self.assertEqual(self.alice.id, response.json()["owner_account_id"])
        self.assertEqual("alice-private", response.json()["owner_username"])
        alice_id = response.json()["id"]
        self.assertEqual([alice_id], [s["id"] for s in self.request("GET", "/api/portal/external-subscriptions", self.alice).json()])
        self.assertEqual([], self.request("GET", "/api/portal/external-subscriptions", self.bob).json())
        admin = self.request("GET", "/api/commerce/admin/external-subscriptions", token=create_admin_token(self.admin.username))
        self.assertEqual({shared.id, alice_id}, {s["id"] for s in admin.json()})
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertIn("no-store", admin.headers["cache-control"])

    def test_cross_owner_and_shared_sources_are_hidden_for_every_action(self):
        other = self.private_source(self.bob)
        shared = self.create_source("Shared")
        for source in (other, shared):
            base = f"/api/portal/external-subscriptions/{source.id}"
            for method, suffix, payload in [
                ("PUT", "", {"name": "Hijacked"}), ("DELETE", "", None),
                ("POST", "/credential", {"url": CANARY_URL}), ("DELETE", "/credential", None),
                ("POST", "/refresh", None), ("GET", "/nodes", None), ("POST", "/snapshot", None),
            ]:
                with self.subTest(source=source.id, action=suffix, method=method), patch.object(service, "fetch_clash_subscription") as fetch:
                    response = self.request(method, base + suffix, self.alice, payload=payload,
                                            snapshot=_snapshot("Private") if suffix == "/snapshot" else None)
                    self.assertEqual(404, response.status, response.body)
                    fetch.assert_not_called()

    def test_portal_and_admin_authentication_boundaries(self):
        path = "/api/portal/external-subscriptions"
        self.assertEqual(401, self.request("GET", path).status)
        self.assertEqual(401, self.request("GET", path, token=create_admin_token(self.admin.username)).status)
        admin_path = "/api/commerce/admin/external-subscriptions"
        self.assertEqual(401, self.request("GET", admin_path, self.alice).status)
        self.assertEqual(403, self.request("GET", admin_path, token=create_admin_token(self.limited_admin.username)).status)
        self.bob.is_active = False
        self.db.commit()
        self.assertEqual(401, self.request("GET", path, self.bob).status)

    def test_names_are_unique_within_scope_but_independent_between_users(self):
        shared = self.create_source("My feed")
        alice = self.private_source()
        bob = self.private_source(self.bob)
        self.assertEqual(3, len({shared.id, alice.id, bob.id}))
        with self.assertRaises(IntegrityError):
            self.private_source()
        self.db.rollback()
        with self.assertRaises(IntegrityError):
            self.create_source("My feed")
        self.db.rollback()

    def test_private_sources_cannot_be_granted_to_a_shared_plan(self):
        source = self.private_source()
        with self.assertRaises(commerce.PlanConfigurationError):
            commerce.create_plan(self.db, SubscriptionPlanCreate(
                name="Leak", price_minor=0, duration_days=30, data_limit=0, inbound_tags=[],
                external_selections=[ExternalSelectionInput(source_id=source.id, mode="all")]))
        self.db.rollback()

    def test_admin_can_manage_private_metadata_credentials_snapshot_and_delete(self):
        source = self.private_source()
        source_id = source.id
        base = f"/api/commerce/admin/external-subscriptions/{source_id}"
        token = create_admin_token(self.admin.username)
        response = self.request("PUT", base, token=token, payload={"name": "Admin edited", "enabled": False})
        self.assertEqual(200, response.status, response.body)
        self.assertEqual(self.alice.id, response.json()["owner_account_id"])
        response = self.request("POST", base + "/snapshot", token=token, snapshot=_snapshot("Imported"))
        self.assertEqual(200, response.status, response.body)
        self.assertEqual(1, response.json()["node_count"])
        response = self.request("GET", base + "/nodes", token=token)
        self.assertEqual("Imported", response.json()["items"][0]["name"])
        with patch.object(service, "_validate_public_https_url", return_value=SimpleNamespace(url=CANARY_URL)):
            response = self.request("POST", base + "/credential", token=token, payload={"url": CANARY_URL})
        self.assertEqual(200, response.status, response.body)
        self.assertNotIn(CANARY_SECRET.encode(), response.body)
        self.assertNotIn(b"url_ciphertext", response.body)
        self.assertTrue(response.json()["credential_configured"])
        self.assertEqual(200, self.request("DELETE", base + "/credential", token=token).status)
        self.assertEqual(204, self.request("DELETE", base, token=token).status)
        self.db.expire_all()
        self.assertIsNone(self.db.get(ExternalSubscriptionSource, source_id))

    def test_owner_lifecycle_and_isolated_node_listing(self):
        source = self.private_source()
        base = f"/api/portal/external-subscriptions/{source.id}"
        response = self.request("POST", base + "/snapshot", self.alice, snapshot=_snapshot("Owner node"))
        self.assertEqual(200, response.status, response.body)
        nodes = self.request("GET", base + "/nodes", self.alice).json()["items"]
        self.assertEqual(["Owner node"], [n["name"] for n in nodes])
        self.assertNotIn("payload_ciphertext", nodes[0])
        self.assertEqual(200, self.request("PUT", base, self.alice, payload={"name": "Renamed"}).status)
        self.assertEqual(204, self.request("DELETE", base, self.alice).status)
        self.assertEqual([], self.request("GET", "/api/portal/external-subscriptions", self.alice).json())

    def test_source_limit_is_transactional_and_user_scoped(self):
        with patch.object(service, "MAX_PRIVATE_SOURCES", 1):
            self.private_source()
            with self.assertRaises(service.ExternalSubscriptionConfigurationError) as raised:
                self.private_source(name="Second")
            self.assertEqual("private_source_limit_exceeded", raised.exception.code)
            self.db.rollback()
            self.private_source(self.bob)
            self.create_source("Another shared")

    def test_private_budget_rejection_keeps_last_good_snapshot(self):
        first = self.private_source()
        second = self.private_source(name="Second")
        self.import_nodes(first, "First")
        self.import_nodes(second, "Second")
        for limits in ({"MAX_PRIVATE_NODES": 2}, {"MAX_PRIVATE_DECRYPTED_BYTES": 1}):
            with patch.multiple(service, **limits), self.assertRaises(service.ExternalSubscriptionConfigurationError) as raised:
                self.import_nodes(first, "First", "Added")
            self.assertEqual("private_overlay_limit_exceeded", raised.exception.code)
            self.db.rollback()
            overlays = service.load_external_overlays_for_user(self.db, self.alice_user.id)
            self.assertEqual(["First", "Second"], [n["name"] for s in overlays for n in s.nodes])

    def test_shared_and_private_nodes_mix_only_into_their_owners_exports(self):
        shared = self.create_source("Shared")
        self.import_nodes(shared, "Shared node")
        plan = self.db.query(SubscriptionPlan).one()
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(
            external_selections=[ExternalSelectionInput(source_id=shared.id, mode="all")]))
        alice = self.private_source()
        bob = self.private_source(self.bob)
        self.import_nodes(alice, "Alice node")
        self.import_nodes(bob, "Bob node")
        for user, present, absent in [(self.alice_user, "Alice node", "Bob node"), (self.bob_user, "Bob node", "Alice node")]:
            overlays = service.load_external_overlays_for_user(self.db, user.id)
            self.assertEqual({"Shared node", present}, {n["name"] for s in overlays for n in s.nodes})
            for client in ("clash", "clash-meta", "shadowrocket"):
                with patch("app.subscription.clash.render_template", return_value=json.dumps({"proxy-groups": [{"name": "Proxy", "type": "select", "proxies": ["DIRECT"]}], "rules": ["MATCH,DIRECT"]})):
                    response = build_subscription_response(UserResponse.model_validate(user), client_type=client, db=self.db, user_id=user.id)
                document = yaml.safe_load(response.body)
                names = [n["name"] for n in document["proxies"]]
                self.assertTrue(any(present in n for n in names), names)
                self.assertFalse(any(absent in n for n in names), names)
        service.update_source(self.db, alice, enabled=False)
        self.assertEqual([shared.id], [s.source_id for s in service.load_external_overlays_for_user(self.db, self.alice_user.id)])
        service.update_source(self.db, alice, enabled=True)
        self.assertEqual({shared.id, alice.id}, {s.source_id for s in service.load_external_overlays_for_user(self.db, self.alice_user.id)})

    def test_private_manual_refresh_is_rate_limited_before_fetch(self):
        source = self.private_source()
        for _ in range(20):
            routes._private_external_rate_limit(self.alice)
        with patch.object(service, "fetch_clash_subscription") as fetch:
            response = self.request("POST", f"/api/portal/external-subscriptions/{source.id}/refresh", self.alice)
            self.assertEqual(429, response.status, response.body)
            fetch.assert_not_called()

    def test_private_url_reuses_public_https_and_ssrf_validation(self):
        for url in ("http://example.com/sub", "https://127.0.0.1/sub", "https://[::1]/sub", "https://169.254.169.254/sub"):
            with self.subTest(url=url):
                response = self.request("POST", "/api/portal/external-subscriptions", self.alice,
                                        payload={"name": "Rejected", "url": url})
                self.assertEqual(422, response.status, response.body)
        self.assertEqual([], self.request("GET", "/api/portal/external-subscriptions", self.alice).json())

    def test_owner_can_replace_url_refresh_and_remove_credential_without_leaks(self):
        source = self.private_source()
        base = f"/api/portal/external-subscriptions/{source.id}"
        fetched = service.FetchedExternalPayload(content=_snapshot("Remote node"), etag=None, last_modified=None)
        with patch.object(service, "_validate_public_https_url", return_value=SimpleNamespace(url=CANARY_URL)), patch.object(service, "fetch_clash_subscription", return_value=fetched) as fetch:
            response = self.request("POST", base + "/credential", self.alice, payload={"url": CANARY_URL})
            self.assertEqual(200, response.status, response.body)
            self.assertTrue(response.json()["credential_configured"])
            self.assertNotIn(CANARY_SECRET.encode(), response.body)
            response = self.request("POST", base + "/refresh", self.alice)
            self.assertEqual(200, response.status, response.body)
            self.assertEqual("ready", response.json()["status"])
            self.assertEqual(2, fetch.call_count)
        response = self.request("DELETE", base + "/credential", self.alice)
        self.assertEqual(200, response.status, response.body)
        self.assertFalse(response.json()["credential_configured"])
        self.assertEqual(1, response.json()["node_count"])
