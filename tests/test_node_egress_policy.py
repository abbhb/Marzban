import socket
import unittest
from unittest.mock import patch

from scripts.node_egress.policy import new_mark, render, resolve_list


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "inbounds": {"p1": "vless", "p2": "vless", "hk": "vless"},
            "direct": ["direct"],
            "default": "direct",
            "routing": {
                "rules": [
                    {"ip": ["geoip:private"], "outboundTag": "block"},
                    {"inboundTag": ["hk"], "outboundTag": "wireguard"},
                    {"inboundTag": ["p1"], "outboundTag": "direct"},
                ]
            },
        }
        self.users = [{"email": "12.u", "mark": 101}]
        self.targets = {"domain": ["domain:youtube.com"], "ip": ["2000::/3"]}

    def test_rules_keep_relative_priority_and_only_match_managed_users(self):
        rules, outs = render(self.base, ["p1", "p2"], self.users, self.targets)
        self.assertEqual(rules[:2], self.base["routing"]["rules"][:2])
        self.assertEqual(rules[8], self.base["routing"]["rules"][2])
        self.assertEqual(
            [r["inboundTag"] for r in rules if r.get("user")],
            [["p1"]] * 5 + [["p2"]] * 5,
        )
        self.assertEqual(len({r["ruleTag"] for r in rules if "ruleTag" in r}), 12)
        self.assertEqual(rules[7]["outboundTag"], "mz6-pending")
        self.assertEqual(rules[-1]["outboundTag"], "mz6-pending")
        self.assertEqual(outs[0]["streamSettings"]["sockopt"]["mark"], 101)
        self.assertTrue(
            outs[0]["streamSettings"]["sockopt"]["happyEyeballs"]["prioritizeIPv6"]
        )

    def test_no_tunnel_override_and_no_changes_when_off(self):
        with self.assertRaises(ValueError):
            render(self.base, ["hk"], self.users, self.targets)
        self.assertEqual(
            render(self.base, [], [], {}), (self.base["routing"]["rules"], [])
        )

    def test_transient_dns_failure_does_not_publish_partial_refresh(self):
        spec = {
            "domains": {"a.test": "a.test", "b.test": "b.test"},
            "ipv6_networks": ["2000::/3"],
        }
        with (
            patch(
                "socket.getaddrinfo",
                side_effect=[
                    [("", "", "", "", ("2606:4700::1", 443))],
                    socket.gaierror(socket.EAI_AGAIN, "timeout"),
                ],
            ),
            self.assertRaises(socket.gaierror),
        ):
            resolve_list(spec)

    def test_public_ipv4_alias_requires_matching_a_and_global_aaaa(self):
        spec = {
            "domains": {"a.test": "a.test"},
            "ipv6_networks": [],
            "ipv4_aliases": {"1.1.1.1": "one.test", "8.8.8.8": "two.test"},
        }

        def lookup(host, *_args):
            values = {
                "a.test": ["2606:4700::1"],
                "one.test": ["1.1.1.1", "2606:4700::1"],
                "two.test": ["1.1.1.1", "2606:4700::2"],
            }[host]
            return [(0, 0, 0, "", (ip, 443)) for ip in values]

        with patch("socket.getaddrinfo", side_effect=lookup):
            targets = resolve_list(spec)
        self.assertEqual(targets["ipv4_aliases"], {"1.1.1.1": "one.test"})
        rules, outs = render(self.base, ["p1"], self.users, targets)
        rule = next(r for r in rules if r.get("ip") == ["1.1.1.1/32"])
        out = next(o for o in outs if o["tag"] == rule["outboundTag"])
        self.assertEqual(out["settings"]["redirect"], "one.test:0")
        self.assertEqual(
            out["streamSettings"]["sockopt"]["mark"], self.users[0]["mark"]
        )
        self.assertEqual(rule["network"], "tcp")

    def test_mark_exhaustion_and_last_slot(self):
        prefix = 100
        used = {(prefix << 16) | i for i in range(1, 65536)}
        with self.assertRaises(ValueError):
            new_mark(prefix, used)
        last = used.pop()
        self.assertEqual(new_mark(prefix, used), last)
