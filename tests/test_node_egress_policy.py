import unittest

from scripts.node_egress.policy import new_mark, render


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

    def test_rules_keep_relative_priority_and_only_match_managed_users(self):
        rules, outs = render(self.base, ["p1", "p2"], self.users)
        self.assertEqual(rules[:2], self.base["routing"]["rules"][:2])
        self.assertEqual(rules[5], self.base["routing"]["rules"][2])
        user_rules = [r for r in rules if r.get("user")]
        self.assertEqual(
            [r["inboundTag"] for r in user_rules], [["p1"]] * 2 + [["p2"]] * 2
        )
        self.assertEqual([r["network"] for r in user_rules], ["tcp", "udp"] * 2)
        self.assertTrue(all("domain" not in r and "ip" not in r for r in user_rules))
        self.assertEqual(user_rules[0]["outboundTag"], outs[0]["tag"])
        self.assertEqual(user_rules[1]["outboundTag"], outs[1]["tag"])
        self.assertEqual(rules[4]["outboundTag"], "mz6-pending")
        self.assertEqual(rules[-1]["outboundTag"], "mz6-pending")
        self.assertEqual(outs[0]["streamSettings"]["sockopt"]["mark"], 101)
        self.assertTrue(
            outs[0]["streamSettings"]["sockopt"]["happyEyeballs"]["prioritizeIPv6"]
        )

    def test_no_tunnel_override_and_no_changes_when_off(self):
        with self.assertRaises(ValueError):
            render(self.base, ["hk"], self.users)
        self.assertEqual(
            render(self.base, [], []), (self.base["routing"]["rules"], [])
        )

    def test_legacy_alias_input_never_redirects_ipv4_literals(self):
        # Old launchers can pass historical targets during a rolling update.
        # They must not enable IPv4-to-domain mapping or additional DNS lookups.
        old = {"ipv4_aliases": {"1.1.1.1": "one.one.one.one"}}
        rules, outs = render(self.base, ["p1"], self.users, old)
        self.assertFalse(any("ip" in r for r in rules if r.get("user")))
        self.assertTrue(all("redirect" not in out.get("settings", {}) for out in outs))
        self.assertEqual((rules, outs), render(self.base, ["p1"], self.users))

    def test_mark_exhaustion_and_last_slot(self):
        prefix = 100
        used = {(prefix << 16) | i for i in range(1, 65536)}
        with self.assertRaises(ValueError):
            new_mark(prefix, used)
        last = used.pop()
        self.assertEqual(new_mark(prefix, used), last)
