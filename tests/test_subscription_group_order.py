"""Persistence, permission and final export checks for policy group ordering."""
import copy
from unittest.mock import patch

import yaml
from pydantic import ValidationError

from app import app
from app.db import get_db, crud
from app.models.admin import AdminCreate
from app.models.user import UserResponse
from app.routers.subscription import build_subscription_response
from app.services import subscription_group_order as service
from app.subscription.clash import ClashConfiguration, EXTERNAL_AGGREGATE_GROUP_NAME
from app.utils.jwt import create_admin_token
from tests.test_mgma import MgmaDatabaseTestCase
from tests.test_private_external_subscriptions import PrivateExternalTests as _HttpHelper

DOCUMENT = {
    "mode": "rule", "rules": ["MATCH,A"],
    "proxy-groups": [
        {"name": "A", "type": "select", "proxies": ["DIRECT", "REJECT"]},
        {"name": EXTERNAL_AGGREGATE_GROUP_NAME, "type": "select", "proxies": ["DIRECT"]},
        {"name": "B", "type": "select", "proxies": ["DIRECT"]},
        {"name": "C", "type": "select", "proxies": ["A", "B"]},
    ],
}
OVERLAY = {"sources": [{"id": 1, "group_name": "Airport", "nodes": [
    {"name": "HK", "type": "ss", "server": "public.example", "port": 443,
     "cipher": "aes-128-gcm", "password": "test-only"},
]}]}


class GroupOrderTests(MgmaDatabaseTestCase):
    request = _HttpHelper.request

    def setUp(self):
        super().setUp()
        self.patches = [patch.object(service, "template_document", return_value=copy.deepcopy(DOCUMENT)),
                        patch("app.utils.jwt.get_secret_key", return_value="group-order-test-secret")]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)

    def test_roundtrip_conflict_and_restore(self):
        self.assertEqual(service.read_group_order(self.db)["group_names"], ["A", "B", "C"])
        saved = service.save_group_order(self.db, service.GroupOrderUpdate(group_names=["C", "A", "B"], revision=0))
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["revision"], 1)
        self.db.expire_all()
        self.assertEqual(service.load_group_order(self.db), ["C", "A", "B"])
        for revision in (0, 2):
            with self.assertRaises(service.GroupOrderConflict):
                service.save_group_order(self.db, service.GroupOrderUpdate(group_names=["A", "B", "C"], revision=revision))
        restored = service.save_group_order(self.db, service.GroupOrderUpdate(group_names=None, revision=1))
        self.assertFalse(restored["enabled"])
        self.assertEqual(restored["group_names"], ["A", "B", "C"])

    def test_invalid_or_external_names_do_not_overwrite(self):
        service.save_group_order(self.db, service.GroupOrderUpdate(group_names=["C", "A", "B"], revision=0))
        for names in ([], ["A", "A", "C"], ["A", "B"], ["A", "B", "missing"],
                      ["A", "B", "C", EXTERNAL_AGGREGATE_GROUP_NAME], ["A", "B", "Airport"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                service.save_group_order(self.db, service.GroupOrderUpdate(group_names=names, revision=1))
            self.assertEqual(service.load_group_order(self.db), ["C", "A", "B"])
        with self.assertRaises(ValidationError):
            service.GroupOrderUpdate(group_names=["A"], revision=-1)

    def test_template_evolution_preserves_saved_order_and_appends_new_groups(self):
        service.save_group_order(self.db, service.GroupOrderUpdate(group_names=["C", "A", "B"], revision=0))
        changed = copy.deepcopy(DOCUMENT)
        changed["proxy-groups"] = [g for g in changed["proxy-groups"] if g["name"] != "B"]
        changed["proxy-groups"].insert(0, {"name": "New", "type": "select", "proxies": ["DIRECT"]})
        with patch.object(service, "template_document", return_value=changed):
            self.assertEqual(service.read_group_order(self.db)["group_names"], ["C", "A", "New"])

    def test_external_groups_stay_last_and_group_contents_are_preserved(self):
        for overlay in (None, OVERLAY):
            with self.subTest(overlay=bool(overlay)), patch("app.subscription.clash.render_template", side_effect=lambda name, context=None:
                    '{}' if name != 'clash/default.yml' else yaml.safe_dump(DOCUMENT)):
                result = yaml.safe_load(ClashConfiguration().render(subscription_group_order=["C", "A", "B"], clash_overlay=overlay, is_meta=True))
            names = [g["name"] for g in result["proxy-groups"]]
            self.assertEqual(names[:3], ["C", "A", "B"])
            self.assertEqual(names[3:], [EXTERNAL_AGGREGATE_GROUP_NAME, "Airport"] if overlay else [EXTERNAL_AGGREGATE_GROUP_NAME])
            self.assertEqual(result["rules"], DOCUMENT["rules"])
            for group in result["proxy-groups"][:3]:
                self.assertEqual(group, next(g for g in DOCUMENT["proxy-groups"] if g["name"] == group["name"]))

    def test_all_three_export_formats_apply_persisted_order_and_fixed_external_block(self):
        service.save_group_order(self.db, service.GroupOrderUpdate(group_names=["C", "A", "B"], revision=0))
        user = self.create_user()
        for client in ("clash", "clash-meta", "shadowrocket"):
            with self.subTest(client=client), patch("app.routers.subscription.load_external_overlays_for_user", return_value=[]), patch(
                "app.subscription.clash.render_template", side_effect=lambda name, context=None:
                '{}' if name != 'clash/default.yml' else yaml.safe_dump(DOCUMENT)):
                result = yaml.safe_load(build_subscription_response(UserResponse.model_validate(user), client_type=client, db=self.db, user_id=user.id).body)
            self.assertEqual([g["name"] for g in result["proxy-groups"]], ["C", "A", "B", EXTERNAL_AGGREGATE_GROUP_NAME])
            self.assertEqual(result["rules"], DOCUMENT["rules"])

    def test_http_requires_sudo_and_returns_validation_conflict_and_no_store(self):
        def review_db():
            with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = review_db
        self.addCleanup(app.dependency_overrides.pop, get_db)
        limited = crud.create_admin(self.db, AdminCreate(username="group-limited", password="test-only", is_sudo=False))
        root = crud.create_admin(self.db, AdminCreate(username="group-root", password="test-only", is_sudo=True))
        endpoint = "/api/subscription/group-order"
        payload = {"group_names": ["C", "A", "B"], "revision": 0}
        for method in ("GET", "PUT"):
            self.assertIn(self.request(method, endpoint, payload=payload if method == "PUT" else None).status, (401, 403))
            self.assertEqual(self.request(method, endpoint, token=create_admin_token(limited.username, False), payload=payload if method == "PUT" else None).status, 403)
        token = create_admin_token(root.username, True)
        initial = self.request("GET", endpoint, token=token)
        self.assertEqual(initial.status, 200)
        self.assertIn("no-store", initial.headers["cache-control"])
        saved = self.request("PUT", endpoint, token=token, payload=payload)
        self.assertEqual(saved.status, 200)
        self.assertEqual(saved.json()["group_names"], payload["group_names"])
        self.assertEqual(self.request("PUT", endpoint, token=token, payload=payload).status, 409)
        payload.update(group_names=["A", "A", "B"], revision=1)
        self.assertEqual(self.request("PUT", endpoint, token=token, payload=payload).status, 422)


# The borrowed ASGI helper class is not part of this module's test suite.
del _HttpHelper
