"""Panel persistence, authorization and fully materialized two-hop subscriptions."""
import copy
from datetime import datetime
import os
import re
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import xray
from app import app
from app.db import crud, get_db
from app.models.admin import AdminCreate
from app.models.user import UserResponse
from app.db.models import ExternalSubscriptionNode, ProxyHost as HostRow
from app.models.proxy import ProxyHost, ProxyTypes, VLESSSettings
from app.routers import system, commerce
from app.routers.subscription import build_subscription_response
from app.services import cascades, external_subscriptions as external
from app.subscription.cascade import apply_cascades, entry_key
from app.subscription.local_nodes import route_id
from app.subscription.share import generate_subscription
from app.utils.jwt import create_admin_token
from tests.test_mgma import MgmaDatabaseTestCase


ENTRY = {"name": "香港 01", "type": "vless", "server": "entry.example", "port": 2501,
         "uuid": "11111111-1111-4111-8111-111111111111", "network": "tcp", "tls": True,
         "flow": "xtls-rprx-vision", "client-fingerprint": "firefox", "udp": True,
         "servername": "www.example.com", "reality-opts": {"public-key": "A" * 43, "short-id": "0123456789abcdef"}}
INBOUND = {"tag": "US", "protocol": "vless", "network": "tcp", "tls": "reality",
           "port": 443, "sni": ["www.example.com"], "host": [], "path": "", "header_type": "",
           "pbk": "B" * 43, "sids": ["0123456789abcdef"], "flow_override": "xtls-rprx-vision"}


class CascadeTests(MgmaDatabaseTestCase):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"EXTERNAL_SUBSCRIPTION_ENCRYPTION_KEY": "cascade-test-key-longer-than-thirty-two-characters"})
        env.start(); self.addCleanup(env.stop)
        config = patch.object(xray.config, "inbounds_by_tag", {"US": INBOUND, "OTHER": INBOUND})
        config.start(); self.addCleanup(config.stop)

    def host(self, mode="replace", entry_id=None):
        model = ProxyHost(remark="US02", address="landing.example", cascade_mode=mode,
                          cascade_entry_id=entry_id,
                          cascade_entry_yaml=None if entry_id else yaml.safe_dump(ENTRY))
        cascades.validate_hosts(self.db, {"US": [model]})
        return crud.update_hosts(self.db, "US", [model], commit=False)[0]

    def cached(self, row):
        return {"id": row.id, "cascade_mode": row.cascade_mode, "remark": row.remark,
                "address": [row.address], "port": None, "path": None, "sni": [], "host": [],
                "tls": None, "alpn": "", "fingerprint": "", "allowinsecure": False,
                "mux_enable": False, "fragment_setting": None, "noise_setting": None,
                "random_user_agent": False}

    def user(self, identity="22222222-2222-4222-8222-222222222222", **values):
        return SimpleNamespace(username="test", used_traffic=0, data_limit=None, expire=None,
                               status="active", inbounds={ProxyTypes.VLESS: ["US"]},
                               proxies={ProxyTypes.VLESS: VLESSSettings(id=identity)}, **values)

    def render(self, row, user=None):
        user = user or self.user()
        with patch.object(xray, "hosts", {"US": [self.cached(row)]}):
            entries = cascades.resolve_for_user(self.db, user, "clash-meta")
            return yaml.safe_load(generate_subscription(user, "clash-meta", False, False, cascade_nodes=entries))

    def source(self, owner=None):
        source = external.create_source(self.db, name="Airport", group_name="Airport", created_by="test")
        external.import_snapshot(self.db, source, yaml.safe_dump({"proxies": [ENTRY]}).encode())
        if owner is not None:
            source.owner_account_id = owner; source.scope_key = owner; self.db.commit()
        return source, source.nodes[0]

    def test_yaml_forms_and_protocol_fields_are_preserved(self):
        for document in (ENTRY, [ENTRY], {"proxies": [ENTRY]}):
            self.assertEqual(cascades.parse_entry_yaml(yaml.safe_dump(document)), ENTRY)
        for kind in ("ss", "vmess", "trojan", "socks5", "hysteria2", "tuic"):
            node = {**ENTRY, "type": kind, "password": "test", "cipher": "aes-128-gcm"}
            self.assertEqual(cascades.parse_entry_yaml(yaml.safe_dump(node)), node)
        for document in ({"proxies": [ENTRY, ENTRY]}, {**ENTRY, "dialer-proxy": "DIRECT"},
                         {**ENTRY, "detour": "private"}, {**ENTRY, "port": 0},
                         {**ENTRY, "xhttp-opts": {"download-settings": {"dialer-proxy": "private"}}}):
            with self.assertRaises(cascades.CascadeError):
                cascades.parse_entry_yaml(yaml.safe_dump(document))
        with self.assertRaises(cascades.CascadeError):
            cascades.parse_entry_yaml("proxies: [&node {name: bad}, *node]")

    def test_replace_preserves_name_per_user_credentials_and_reality(self):
        row = self.host()
        self.assertNotIn(ENTRY["uuid"], row.cascade_entry_ciphertext)
        self.assertEqual(cascades.parse_entry_yaml(row.cascade_entry_yaml), ENTRY)
        self.assertEqual(ProxyHost.model_validate(row).cascade_mode, "replace")
        for identity in ("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"):
            document = self.render(row, self.user(identity))
            landing = next(n for n in document["proxies"] if n["name"] == "US02")
            self.assertEqual(landing["uuid"], identity)
            self.assertEqual(landing["flow"], "xtls-rprx-vision")
            self.assertEqual(landing["packet-encoding"], "xudp")
            helper = next(n for n in document["proxies"] if n["name"] == landing["dialer-proxy"])
            self.assertEqual({**helper, "name": ENTRY["name"]}, ENTRY)
            for group in document["proxy-groups"]:
                self.assertNotIn(helper["name"], group.get("proxies", []))

    def test_additional_mode_and_route_identity_are_stable(self):
        row = self.host("additional")
        document = self.render(row)
        by_name = {n["name"]: n for n in document["proxies"]}
        self.assertNotIn("dialer-proxy", by_name["US02"])
        self.assertIn("dialer-proxy", by_name["US02 · 级联"])
        old = self.cached(row)
        old.pop("id"); old.pop("cascade_mode")
        self.assertEqual(route_id(old, inbound=INBOUND), route_id(self.cached(row), inbound=INBOUND))

    def test_user_detail_omits_unrepresentable_share_links_without_breaking(self):
        row = self.host()
        with patch.object(xray, "hosts", {"US": [self.cached(row)]}):
            response = UserResponse(username="alice", status="active", used_traffic=0,
                                    created_at=datetime.now(), proxies=self.user().proxies,
                                    inbounds={"vless": ["US"]})
        self.assertEqual(response.links, [])

    def test_plan_route_selection_denies_entry_as_well_as_landing(self):
        row = self.host()
        user = self.user(local_node_selections={"US": []})
        document = self.render(row, user)
        self.assertEqual(document["proxies"], [])

    def test_external_refresh_updates_payload_and_preserves_disappeared_reference(self):
        source, node = self.source()
        row = self.host(entry_id=node.id)
        self.db.commit()
        updated = {**ENTRY, "uuid": "44444444-4444-4444-8444-444444444444"}
        external.import_snapshot(self.db, source, yaml.safe_dump({"proxies": [updated]}).encode())
        document = self.render(row)
        self.assertEqual(next(n for n in document["proxies"] if n["server"] == "entry.example")["uuid"], updated["uuid"])
        other = {**ENTRY, "name": "Other", "server": "other.example"}
        external.import_snapshot(self.db, source, yaml.safe_dump({"proxies": [other]}).encode())
        self.assertFalse(self.db.get(ExternalSubscriptionNode, node.id).is_active)
        with self.assertRaisesRegex(cascades.CascadeError, "cascade_entry_unavailable"):
            self.render(row)
        external.import_snapshot(self.db, source, yaml.safe_dump({"proxies": [updated]}).encode())
        self.assertTrue(self.db.get(ExternalSubscriptionNode, node.id).is_active)
        self.render(row)

    def test_private_disabled_and_deleted_sources_cannot_be_used(self):
        source, node = self.source()
        self.host(entry_id=node.id)
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            commerce.admin_delete_external_subscription(source.id, self.db, None)
        self.assertEqual(error.exception.status_code, 409)
        source.enabled = False; self.db.commit()
        with self.assertRaises(cascades.CascadeError): cascades.external_entry(self.db, node.id)
        source.enabled = True; source.owner_account_id = 123; source.scope_key = 123; self.db.commit()
        self.assertEqual(cascades.entry_choices(self.db, selected_id=node.id), [])
        with self.assertRaises(cascades.CascadeError): cascades.external_entry(self.db, node.id)

    def test_helper_collisions_and_dynamic_groups_do_not_expose_entry(self):
        key = entry_key(ENTRY)
        document = {"proxies": [{"name": key}, {"name": "US", "dialer-proxy": key}],
                    "proxy-groups": [{"name": "ALL", "include-all-proxies": True, "exclude-filter": "private"}]}
        result = apply_cascades(copy.deepcopy(document), {key: ENTRY})
        helper = result["proxies"][-1]["name"]
        self.assertNotEqual(helper, key)
        self.assertEqual(result["proxies"][1]["dialer-proxy"], helper)
        regex = re.compile(result["proxy-groups"][0]["exclude-filter"])
        self.assertTrue(regex.search(helper)); self.assertTrue(regex.search("private"))

    def test_unsupported_clients_and_unavailable_entries_return_safe_errors(self):
        row = self.host()
        with patch.object(xray, "hosts", {"US": [self.cached(row)]}):
            for agent in ("SFA/1.0", "Shadowrocket/1.0", "clash/1.0", "v2rayN/7.0"):
                with self.subTest(agent=agent), self.assertRaises(HTTPException) as error:
                    build_subscription_response(self.user(), user_agent=agent, db=self.db)
                self.assertEqual(error.exception.status_code, 422)
                self.assertEqual(error.exception.detail, "cascade_requires_mihomo")
            row.cascade_entry_ciphertext = "corrupt"
            self.db.flush()
            with self.assertRaises(HTTPException) as error:
                build_subscription_response(self.user(), user_agent="mihomo", db=self.db)
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn(ENTRY["uuid"], error.exception.detail)

    def test_invalid_multi_inbound_save_is_atomic(self):
        row = self.host(); self.db.commit()
        values = {"US": [ProxyHost(remark="Changed", address="changed.example")],
                  "OTHER": [ProxyHost(remark="Invalid", address="other.example", cascade_mode="replace")]}
        with patch.object(xray.hosts, "update") as reload:
            with self.assertRaises(HTTPException): system.modify_hosts(values, self.db, None)
            reload.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(HostRow, row.id).remark, "US02")

    def test_successful_multi_inbound_save_retains_encrypted_config(self):
        values = {"US": [ProxyHost(remark="US02", address="landing.example", cascade_mode="replace", cascade_entry_yaml=yaml.safe_dump(ENTRY))]}
        with patch.object(xray.hosts, "update") as reload:
            result = system.modify_hosts(values, self.db, None)
            reload.assert_called_once()
        self.assertEqual(result["US"][0].cascade_mode, "replace")
        self.assertNotIn(ENTRY["uuid"], result["US"][0].cascade_entry_ciphertext)

    def test_entry_management_requires_sudo_and_preview_never_echoes_credentials(self):
        def database():
            yield self.db
        app.dependency_overrides[get_db] = database
        self.addCleanup(app.dependency_overrides.pop, get_db)
        limited = crud.create_admin(self.db, AdminCreate(username="cascade-limited", password="test-only", is_sudo=False))
        root = crud.create_admin(self.db, AdminCreate(username="cascade-root", password="test-only", is_sudo=True))
        client = TestClient(app)
        with patch("app.utils.jwt.get_secret_key", return_value="cascade-http-test-secret"):
            for admin in (None, limited):
                headers = {} if admin is None else {"Authorization": "Bearer " + create_admin_token(admin.username, admin.is_sudo)}
                self.assertIn(client.get("/api/hosts/cascade-entries", headers=headers).status_code, (401, 403))
                self.assertIn(client.post("/api/hosts/cascade-preview", headers=headers, json={"yaml": yaml.safe_dump(ENTRY)}).status_code, (401, 403))
            headers = {"Authorization": "Bearer " + create_admin_token(root.username, True)}
            response = client.post("/api/hosts/cascade-preview", headers=headers, json={"yaml": yaml.safe_dump(ENTRY)})
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertNotIn(ENTRY["uuid"], response.text)
            self.assertEqual(response.json()["name"], ENTRY["name"])
