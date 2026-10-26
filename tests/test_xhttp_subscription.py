"""XHTTP export contracts, using synthetic users and endpoints only."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.subscription.clash import ClashConfiguration, ClashMetaConfiguration
from app.subscription.xhttp import mihomo_xhttp_options, mihomo_xhttp_profiles
from app.xray.config import XRayConfig
from app.models.proxy import ProxyTypes


def xhttp_settings():
    return {
        "path": "/images/synthetic/",
        "mode": "packet-up",
        "extra": {
            "xmux": {"maxConcurrency": "16-32", "hKeepAlivePeriod": 0},
            "downloadSettings": {
                "address": "cdn.example.test",
                "port": 443,
                "network": "xhttp",
                "security": "tls",
                "tlsSettings": {
                    "serverName": "cdn.example.test", "alpn": ["h2"],
                    "fingerprint": "chrome",
                    "certificates": [{"keyFile": "/server/private.key"}],
                },
                "xhttpSettings": {
                    "path": "/images/synthetic/",
                    "xmux": {"maxConcurrency": 16, "hMaxReusableSecs": "1800-3000"},
                },
            },
        },
    }


def inbound(network="xhttp"):
    config = XRayConfig({
        "inbounds": [{
            "tag": "TEST_XHTTP", "listen": "127.0.0.1", "port": 10085,
            "protocol": "vless", "settings": {"clients": [], "decryption": "none"},
            "streamSettings": {"network": network, "security": "none",
                               f"{network}Settings": xhttp_settings()},
        }],
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
    })
    resolved = copy.deepcopy(config.inbounds_by_tag["TEST_XHTTP"])
    # Public TLS is terminated by the reverse proxy; host settings describe it.
    resolved.update(port=8443, tls="tls", sni="origin.example.test", alpn="h2",
                    host="origin.example.test", path="/images/synthetic/")
    return resolved


class XhttpSubscriptionTests(unittest.TestCase):
    def test_resolve_and_export_split_transport_with_per_user_credentials(self):
        source = inbound()
        before = copy.deepcopy(source)
        exports = []
        for user_id in ("synthetic-user-one", "synthetic-user-two"):
            conf = ClashMetaConfiguration()
            conf.add("XHTTP", "origin.example.test", source,
                     {"id": user_id, "flow": "xtls-rprx-vision"})
            exports.append(conf.data["proxies"][0])
        node = exports[0]
        self.assertEqual(node["network"], "xhttp")
        self.assertEqual(node["uuid"], "synthetic-user-one")
        self.assertEqual(exports[1]["uuid"], "synthetic-user-two")
        self.assertNotIn("flow", node)
        opts = node["xhttp-opts"]
        self.assertEqual(opts["mode"], "packet-up")
        self.assertEqual(opts["host"], "origin.example.test")
        self.assertEqual(opts["reuse-settings"], {"max-concurrency": "16-32", "h-keep-alive-period": 0})
        down = opts["download-settings"]
        self.assertEqual(down["server"], "cdn.example.test")
        self.assertTrue(down["tls"])
        self.assertEqual(down["alpn"], ["h2"])
        self.assertEqual(down["reuse-settings"]["max-concurrency"], "16")
        self.assertNotIn("certificates", down)
        self.assertNotIn("private.key", json.dumps(node))
        self.assertEqual(source, before)

    def test_splithttp_alias_uses_xhttp_and_its_own_reuse_instead_of_sing_mux(self):
        source = inbound("splithttp")
        source["mux_enable"] = True
        conf = ClashMetaConfiguration()
        conf.add("XHTTP", "origin.example.test", source, {"id": "synthetic-id"})
        node = conf.data["proxies"][0]
        self.assertEqual(node["network"], "xhttp")
        self.assertNotIn("splithttp-opts", node)
        self.assertNotIn("smux", node)
        self.assertIn("download-settings", node["xhttp-opts"])

    def test_legacy_clash_still_omits_xhttp(self):
        conf = ClashConfiguration()
        conf.add("XHTTP", "origin.example.test", inbound(), {"id": "synthetic-id"})
        self.assertEqual(conf.data["proxies"], [])

    def test_top_level_settings_and_downlink_tls_clear_inherited_reality(self):
        source = xhttp_settings()
        source.update(source.pop("extra"))
        source.update(scMaxEachPostBytes=1000000, scMinPostsIntervalMs=30)
        result = mihomo_xhttp_options(source)
        self.assertEqual(result["sc-max-each-post-bytes"], "1000000")
        self.assertEqual(result["download-settings"]["reality-opts"], {"public-key": ""})
        result["download-settings"]["alpn"].append("http/1.1")
        self.assertEqual(source["downloadSettings"]["tlsSettings"]["alpn"], ["h2"])

    def test_unsupported_download_transport_is_rejected(self):
        source = xhttp_settings()
        source["extra"]["downloadSettings"]["network"] = "ws"
        with self.assertRaisesRegex(ValueError, "xhttp transport"):
            mihomo_xhttp_options(source)

    def test_extra_replaces_outer_options_but_retains_host_path_and_mode(self):
        result = mihomo_xhttp_options({
            "host": "origin.example.test", "path": "/outer/", "mode": "packet-up",
            "headers": {"Ignored": "outer"}, "xmux": {"maxConcurrency": 99},
            "extra": {
                "host": "ignored.example.test", "path": "/ignored/", "mode": "stream-one",
                "headers": {"Selected": "extra"}, "xmux": {"maxConcurrency": 16},
            },
        })
        self.assertEqual(result["host"], "origin.example.test")
        self.assertEqual(result["path"], "/outer/")
        self.assertEqual(result["mode"], "packet-up")
        self.assertEqual(result["headers"], {"Selected": "extra"})
        self.assertEqual(result["reuse-settings"]["max-concurrency"], "16")

    def test_download_without_explicit_sni_uses_its_own_address_and_verifies_tls(self):
        result = mihomo_xhttp_options({"downloadSettings": {
            "address": "cdn.example.test", "security": "tls", "tlsSettings": {},
        }})["download-settings"]
        self.assertEqual(result["servername"], "cdn.example.test")
        self.assertEqual(result["host"], "cdn.example.test")
        self.assertFalse(result["skip-cert-verify"])
        self.assertEqual(result["reality-opts"], {"public-key": ""})

    def test_named_profiles_preserve_each_users_credentials_and_group_names(self):
        source = inbound()
        source["xhttpProfiles"] = [
            {"label": "P2 direct", "address": "origin.example.test", "port": 443,
             "streamSettings": {
                 "network": "xhttp", "security": "reality",
                 "realitySettings": {"publicKey": "synthetic-public", "shortId": "abcd",
                                     "serverName": "front.example.test", "privateKey": "server-secret"},
                 "xhttpSettings": {"path": "/images/synthetic/", "mode": "packet-up"}}},
            {"label": "P3 CDN", "address": "cdn.example.test", "port": 443,
             "streamSettings": {
                 "network": "xhttp", "security": "tls",
                 "tlsSettings": {"serverName": "cdn.example.test", "alpn": ["h2"]},
                 "xhttpSettings": {"path": "/images/synthetic/", "mode": "packet-up"}}},
        ]
        before = copy.deepcopy(source)
        for user in ("synthetic-one", "synthetic-two"):
            conf = ClashMetaConfiguration()
            conf.add("US02", "origin.example.test", source, {"id": user})
            first, second = conf.data["proxies"]
            self.assertEqual([n["uuid"] for n in conf.data["proxies"]], [user, user])
            self.assertEqual(conf.proxy_remarks, ["US02 · P2 direct", "US02 · P3 CDN"])
            self.assertTrue(first["reality-opts"]["support-x25519mlkem768"])
            self.assertEqual(second["reality-opts"], {"public-key": ""})
            self.assertNotIn("download-settings", first["xhttp-opts"])
            self.assertNotIn("server-secret", json.dumps(conf.data))
            second["alpn"].append("http/1.1")
        self.assertEqual(source, before)

    def test_downlink_reality_enables_mlkem_and_does_not_export_server_keys(self):
        opts = mihomo_xhttp_options({"downloadSettings": {
            "network": "xhttp", "security": "reality", "address": "origin.example.test", "port": 443,
            "realitySettings": {"publicKey": "synthetic-public", "shortId": "abcd", "privateKey": "server-secret"},
        }})["download-settings"]
        self.assertTrue(opts["reality-opts"]["support-x25519mlkem768"])
        self.assertNotIn("server-secret", json.dumps(opts))

    def test_reality_vision_export_enables_mlkem(self):
        source = inbound()
        source.update(network="tcp", tls="reality", pbk="synthetic-public", sid="abcd")
        conf = ClashMetaConfiguration()
        conf.add("Vision", "origin.example.test", source, {"id": "synthetic-id", "flow": "xtls-rprx-vision"})
        self.assertTrue(conf.data["proxies"][0]["reality-opts"]["support-x25519mlkem768"])

    def test_profile_validation_rejects_other_backend_paths_and_duplicate_names(self):
        conf = ClashMetaConfiguration()
        conf.add("XHTTP", "origin.example.test", inbound(), {"id": "synthetic-id"})
        base = conf.data["proxies"][0]
        invalid = [
            [{"label": "a"}, {"label": "a"}], {},
            [{"label": "a", "streamSettings": {"network": "ws"}}],
            [{"label": "a", "port": 0, "streamSettings": {"network": "xhttp"}}],
            [{"label": "a", "streamSettings": {"network": "xhttp", "xhttpSettings": {"path": "/other/"}}}],
        ]
        for profiles in invalid:
            with self.subTest(profiles=profiles), self.assertRaises(ValueError):
                mihomo_xhttp_profiles(base, profiles)

    def test_profiles_are_exported_only_for_granted_inbounds_and_group_mapping(self):
        from app import xray
        from app.subscription.share import process_inbounds_and_tags
        source = inbound()
        source["xhttpProfiles"] = [{"label": "P2 direct"}, {"label": "P3 CDN"}]
        hosts = {"XHTTP": [{
            "sni": ["origin.example.test"], "host": ["origin.example.test"],
            "address": ["origin.example.test"], "path": None, "port": None,
            "tls": None, "alpn": None, "fingerprint": None, "allowinsecure": None,
            "mux_enable": False, "fragment_setting": None, "noise_setting": None,
            "random_user_agent": False, "remark": "US02 {USERNAME}",
        }]}
        credentials = MagicMock()
        credentials.model_dump.return_value = {"id": "synthetic-user"}
        for granted in ([], ["XHTTP"]):
            conf = ClashMetaConfiguration()
            conf.render = lambda **kwargs: conf.data
            with patch.object(xray, "config", SimpleNamespace(inbounds_by_tag={"XHTTP": source})), patch.object(xray, "hosts", hosts):
                result = process_inbounds_and_tags(
                    {ProxyTypes.VLESS: granted}, {ProxyTypes.VLESS: credentials},
                    {"USERNAME": "test"}, conf,
                )
            expected = ["US02 test · P2 direct", "US02 test · P3 CDN"] if granted else []
            self.assertEqual([n["name"] for n in result["proxies"]], expected)
            self.assertEqual(conf.inbound_proxy_names.get("XHTTP", []), expected)


if __name__ == "__main__":
    unittest.main()
