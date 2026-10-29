"""DNS must fail closed across authorized subscription variations."""

import copy
import unittest
from unittest.mock import patch

import yaml

from app.subscription.clash import ClashMetaConfiguration, PRIMARY_PROXY_GROUP_NAME
from app.subscription.dns_security import BOOTSTRAP_DOH, secure_mihomo_dns


def document():
    return {
        "proxies": [{"name": "allowed", "type": "vless", "server": "192.0.2.1"}],
        "proxy-groups": [{"name": PRIMARY_PROXY_GROUP_NAME, "type": "select", "proxies": ["allowed"]}],
        "rules": ["DOMAIN,panel.example,DIRECT", "MATCH," + PRIMARY_PROXY_GROUP_NAME],
    }


class DnsSecurityTests(unittest.TestCase):
    def test_normal_queries_and_direct_connections_have_no_direct_or_system_fallback(self):
        value = document()
        before = copy.deepcopy(value)
        secure_mihomo_dns(value, PRIMARY_PROXY_GROUP_NAME, "https://panel.example/sub")
        dns = value["dns"]
        self.assertTrue(all(server.startswith("https://") and server.endswith("#" + PRIMARY_PROXY_GROUP_NAME)
                            for server in dns["nameserver"]))
        self.assertEqual(dns["fallback"], [])
        self.assertEqual(dns["direct-nameserver"], [])
        self.assertEqual(dns["default-nameserver"], list(BOOTSTRAP_DOH))
        self.assertEqual(dns["proxy-server-nameserver"], list(BOOTSTRAP_DOH))
        self.assertTrue(all(server.startswith("https://") for server in BOOTSTRAP_DOH))
        self.assertNotIn("system", yaml.safe_dump(dns))
        self.assertTrue(dns["respect-rules"])
        self.assertFalse(dns["prefer-h3"])
        self.assertFalse(dns["ipv6"])
        self.assertEqual(dns["nameserver-policy"], {"panel.example": list(BOOTSTRAP_DOH)})
        self.assertFalse(value["clash-for-android"]["append-system-dns"])
        self.assertEqual(value["rules"], before["rules"])
        self.assertEqual(value["proxies"], before["proxies"])
        self.assertEqual(value["proxy-groups"], before["proxy-groups"])

    def test_no_corporate_addresses_domains_or_interface_names_are_pinned(self):
        value = document()
        secure_mihomo_dns(value, PRIMARY_PROXY_GROUP_NAME, "")
        self.assertEqual(value["dns"]["nameserver-policy"], {})
        self.assertNotIn("route-exclude-address", value["tun"])
        self.assertNotIn("enable", value["tun"])
        self.assertTrue(value["ipv6"])
        self.assertTrue(value["tun"]["strict-route"])
        self.assertEqual(value["tun"]["dns-hijack"], ["any:53", "tcp://any:53"])
        self.assertTrue(value["tun"]["inet6-address"])

    def test_empty_deleted_cyclic_or_direct_capable_selectors_cannot_send_dns_directly(self):
        for members in ([], ["missing"], ["allowed", "DIRECT"], ["GLOBAL"],
                        [PRIMARY_PROXY_GROUP_NAME], ["child"]):
            with self.subTest(members=members):
                value = document()
                value["proxy-groups"][0]["proxies"] = members
                value["proxy-groups"].append({"name": "child", "proxies": ["PASS"]})
                secure_mihomo_dns(value, PRIMARY_PROXY_GROUP_NAME, "")
                self.assertTrue(all(server.endswith("#REJECT") for server in value["dns"]["nameserver"]))

    def test_nested_authorized_external_source_and_reject_are_safe(self):
        value = document()
        value["proxy-groups"][0]["proxies"] = ["external", "REJECT"]
        value["proxy-groups"].append({"name": "external", "proxies": ["allowed"]})
        secure_mihomo_dns(value, PRIMARY_PROXY_GROUP_NAME, "")
        self.assertTrue(all(server.endswith("#" + PRIMARY_PROXY_GROUP_NAME) for server in value["dns"]["nameserver"]))

    def test_unexpanded_providers_and_direct_type_nodes_are_not_trusted(self):
        for key in ("use", "include-all", "include-all-proxies", "include-all-providers"):
            value = document()
            value["proxy-groups"][0][key] = ["provider"]
            secure_mihomo_dns(value, PRIMARY_PROXY_GROUP_NAME, "")
            self.assertTrue(all(server.endswith("#REJECT") for server in value["dns"]["nameserver"]))
        value = document()
        value["proxies"][0]["type"] = "direct"
        secure_mihomo_dns(value, PRIMARY_PROXY_GROUP_NAME, "")
        self.assertTrue(all(server.endswith("#REJECT") for server in value["dns"]["nameserver"]))

    def test_security_is_opt_in_meta_only_and_applied_after_plan_restrictions(self):
        for meta, opted_in, enabled in ((True, True, True), (False, True, True),
                                       (True, False, True), (True, True, False)):
            value = document()
            value["x-mgma-secure-dns"] = opted_in
            with self.subTest(meta=meta, opted_in=opted_in, enabled=enabled), \
                 patch("app.subscription.clash.render_template", side_effect=lambda name, context=None:
                       yaml.safe_dump(value) if name == "clash/default.yml" else "{}"):
                result = yaml.safe_load(ClashMetaConfiguration().render(
                    is_meta=meta, secure_dns=enabled, plan_group_members={PRIMARY_PROXY_GROUP_NAME: []}))
            self.assertNotIn("x-mgma-secure-dns", result)
            self.assertEqual("dns" in result, meta and opted_in and enabled)
            if "dns" in result:
                self.assertEqual(result["proxy-groups"][0]["proxies"], ["REJECT"])
                self.assertTrue(all(server.endswith("#" + PRIMARY_PROXY_GROUP_NAME) for server in result["dns"]["nameserver"]))

    def test_real_easyus_meta_template_enables_security_but_other_formats_do_not(self):
        with patch("app.subscription.clash.CLASH_SUBSCRIPTION_TEMPLATE", "clash/easyus.yml"):
            builder = ClashMetaConfiguration()
            for meta, enabled in ((True, True), (False, True), (True, False)):
                result = yaml.safe_load(builder.render(is_meta=meta, secure_dns=enabled))
                self.assertEqual("dns" in result, meta and enabled)
                self.assertNotIn("x-mgma-secure-dns", result)
