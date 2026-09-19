"""Synthetic-only tests: no external subscriptions or running proxies."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from app.subscription.clash import merge_clash_overlay
from app.subscription.shadowrocket import prepare_shadowrocket, ShadowrocketConversionError
from app.subscription.share import generate_subscription


def document():
    return {
        "proxies": [
            {"name": "美国直连", "type": "vless", "server": "example.test", "port": 443,
             "uuid": "synthetic-id", "tls": True, "flow": "xtls-rprx-vision",
             "reality-opts": {"public-key": "synthetic-public-key", "short-id": "1234"}},
            {"name": "香港直连", "type": "ss", "server": "hk.example.test", "port": 443,
             "cipher": "aes-128-gcm", "password": "synthetic-password"},
        ],
        "proxy-groups": [
            {"name": "美国", "type": "select", "include-all-proxies": True, "filter": "美国直连"},
            {"name": "香港", "type": "select", "proxies": ["美国"], "include-all-proxies": True, "filter": "香港直连"},
            {"name": "🚀 节点选择", "type": "select", "proxies": ["美国", "香港", "DIRECT"]},
        ],
        "rules": ["DOMAIN,example.test,香港", "GEOIP,CN,DIRECT", "MATCH,🚀 节点选择"],
        "dns": {"enable": True, "nameserver": ["223.5.5.5"]},
    }


class ShadowrocketTests(unittest.TestCase):
    def test_materializes_filters_preserving_fallback_order_and_original(self):
        original = document()
        before = copy.deepcopy(original)
        converted = prepare_shadowrocket(original)
        self.assertEqual(converted["proxy-groups"][0]["proxies"], ["美国直连"])
        self.assertEqual(converted["proxy-groups"][1]["proxies"], ["美国", "香港直连"])
        self.assertNotIn("filter", converted["proxy-groups"][1])
        self.assertEqual(converted["proxies"], original["proxies"])
        self.assertEqual(converted["rules"], original["rules"])
        self.assertEqual(converted["dns"], original["dns"])
        self.assertEqual(original, before)

    def test_external_nodes_remain_in_source_group_and_keep_advanced_options(self):
        nodes = [
            {"name": "香港直连 XHTTP", "type": "vless", "server": "x.example.test", "port": 443,
             "network": "xhttp", "encryption": "synthetic-encryption",
             "ech-opts": {"enable": True, "query-server-name": "ech.example.test"},
             "xhttp-opts": {"mode": "auto", "path": "/test", "download-settings": {"address": "d.example.test"}}},
            {"name": "HY2", "type": "hysteria2", "server": "h.example.test", "port": 443,
             "password": "synthetic-password", "ports": "20000-30000", "mport": "20000-30000"},
        ]
        merged = merge_clash_overlay(document(), {"sources": [{"id": 1, "group_name": "第三方", "nodes": nodes}]}, is_meta=True)
        converted = prepare_shadowrocket(merged)
        self.assertEqual(merged["proxies"], converted["proxies"])
        groups = {g["name"]: g for g in converted["proxy-groups"]}
        self.assertEqual(groups["香港"]["proxies"], ["美国", "香港直连"])
        self.assertIn("MGMA · External", groups["🚀 节点选择"]["proxies"])
        self.assertEqual(len(groups["第三方"]["proxies"]), 2)

    def test_empty_group_rejects_instead_of_direct(self):
        source = document()
        source["proxy-groups"][0]["filter"] = "unmatched"
        self.assertEqual(prepare_shadowrocket(source)["proxy-groups"][0]["proxies"], ["REJECT"])

    def test_invalid_or_cyclic_references_rejected_without_secrets(self):
        for members in (["not-a-node"], ["美国"], ["香港"]):
            source = document()
            source["proxy-groups"][0]["proxies"] = members
            with self.assertRaises(ShadowrocketConversionError) as raised:
                prepare_shadowrocket(source)
            self.assertNotIn("synthetic-password", str(raised.exception))

    def test_invalid_filters_and_providers_rejected(self):
        source = document()
        source["proxy-groups"][0]["filter"] = "["
        with self.assertRaises(ShadowrocketConversionError):
            prepare_shadowrocket(source)
        source = document()
        source["proxy-providers"] = {"remote": {"url": "https://secret.example.test"}}
        with self.assertRaises(ShadowrocketConversionError):
            prepare_shadowrocket(source)

    def test_export_yaml_preserves_nodes_and_rules_without_base64(self):
        user = SimpleNamespace(proxies={}, inbounds={})
        overlay = {"sources": []}
        with patch("app.subscription.share.generate_clash_subscription", return_value=yaml.safe_dump(document())) as render:
            output = generate_subscription(user, "shadowrocket", False, False, overlay)
        self.assertTrue(render.call_args.kwargs["is_meta"])
        self.assertIs(render.call_args.kwargs["clash_overlay"], overlay)
        parsed = yaml.safe_load(output)
        self.assertEqual(len(parsed["proxies"]), 2)
        self.assertEqual(parsed["rules"], document()["rules"])
        self.assertEqual(parsed["proxy-groups"][0]["proxies"], ["美国直连"])


if __name__ == "__main__":
    unittest.main()
