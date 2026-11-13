"""The dedicated WG node must not provide an unmarked direct escape path."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.hy03_wg_us01.launch import DENY, DNS_TAG, EGRESS, INBOUND, SOURCE, prepare
from scripts.hy03_wg_us01 import policy


def document():
    return {
        "inbounds": [
            {"tag": "API_INBOUND", "protocol": "dokodemo-door"},
            {"tag": INBOUND, "protocol": "hysteria"},
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "BLOCK", "protocol": "blackhole"},
        ],
        "routing": {"rules": [
            {"inboundTag": ["API_INBOUND"], "outboundTag": "API"},
            {"ip": ["geoip:private"], "outboundTag": "BLOCK"},
            {"inboundTag": ["other"], "outboundTag": "direct"},
        ]},
    }


class DedicatedWireGuardTests(unittest.TestCase):
    def test_dns_and_hysteria_share_source_bound_egress(self):
        data = prepare(document())
        self.assertEqual(data["outbounds"][0], {"tag": DENY, "protocol": "blackhole"})
        via = next(item for item in data["outbounds"] if item["tag"] == EGRESS)
        self.assertEqual(via["sendThrough"], SOURCE)
        self.assertEqual(via["streamSettings"]["sockopt"]["domainStrategy"], "ForceIPv4")
        self.assertEqual(data["dns"]["tag"], DNS_TAG)
        self.assertEqual(data["routing"]["rules"][-1]["inboundTag"], [INBOUND, DNS_TAG])
        self.assertEqual(data["routing"]["rules"][-1]["outboundTag"], EGRESS)
        self.assertEqual(data["routing"]["rules"][1]["outboundTag"], "BLOCK")

    def test_catchall_or_targeted_direct_rule_is_rejected(self):
        for incoming in (None, [INBOUND], [DNS_TAG]):
            data = document()
            rule = {"outboundTag": "direct"}
            if incoming:
                rule["inboundTag"] = incoming
            data["routing"]["rules"].insert(1, rule)
            with self.subTest(incoming=incoming), self.assertRaises(ValueError):
                prepare(data)

    def test_missing_inbound_or_reserved_outbound_is_rejected(self):
        for mutation in ("missing", "reserved"):
            data = document()
            if mutation == "missing":
                data["inbounds"].pop()
            else:
                data["outbounds"].append({"tag": EGRESS, "protocol": "freedom"})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                prepare(data)


class SourcePolicyTests(unittest.TestCase):
    def test_installs_kill_switch_and_unreachable_route_before_rule(self):
        calls = []
        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            if args[:5] == ["ip", "-j", "-4", "rule", "show"]:
                return SimpleNamespace(stdout=json.dumps([]), returncode=0)
            if args[:6] == ["ip", "-j", "-4", "route", "show", "table"]:
                return SimpleNamespace(stdout="", returncode=2)
            if args[:3] == ["nft", "list", "table"]:
                return SimpleNamespace(stdout="", returncode=1)
            return SimpleNamespace(stdout="", returncode=0)
        with patch.object(policy, "run", side_effect=fake_run):
            policy.ensure()
        cmds = [item[0] for item in calls]
        nft_index = next(i for i, cmd in enumerate(cmds) if cmd == ["nft", "-f", "-"])
        unreachable_index = next(i for i, cmd in enumerate(cmds) if "unreachable" in cmd)
        rule_index = next(i for i, cmd in enumerate(cmds) if cmd[:4] == ["ip", "-4", "rule", "add"])
        self.assertLess(nft_index, unreachable_index)
        self.assertLess(unreachable_index, rule_index)
        self.assertIn('ip saddr 10.66.66.5 oifname != "wg-us01"', calls[nft_index][1]["input_text"])

    def test_refuses_to_override_existing_foreign_policy(self):
        foreign = [{"priority": policy.PRIORITY, "src": "192.0.2.1", "table": "main"}]
        with patch.object(policy, "run", return_value=SimpleNamespace(stdout=json.dumps(foreign), returncode=0)) as run:
            with self.assertRaises(RuntimeError):
                policy.ensure()
            self.assertEqual(run.call_count, 1)

    def test_idempotent_for_its_own_policy(self):
        def fake_run(args, **kwargs):
            if args[:5] == ["ip", "-j", "-4", "rule", "show"]:
                return SimpleNamespace(stdout=json.dumps([{"priority": 14200, "src": SOURCE, "table": "14200"}]), returncode=0)
            if args[:6] == ["ip", "-j", "-4", "route", "show", "table"]:
                return SimpleNamespace(stdout=json.dumps([
                    {"type": "unreachable", "dst": "default", "metric": 32760},
                    {"dst": "default", "dev": "wg-us01", "metric": 100},
                ]), returncode=0)
            if args[:3] == ["nft", "list", "table"]:
                return SimpleNamespace(stdout='chain output hook output 10.66.66.5 "wg-us01" reject', returncode=0)
            return SimpleNamespace(stdout="", returncode=0)
        with patch.object(policy, "run", side_effect=fake_run) as run:
            policy.ensure()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertFalse(any(cmd[:4] == ["ip", "-4", "rule", "add"] for cmd in commands))
        self.assertNotIn(["nft", "-f", "-"], commands)


if __name__ == "__main__":
    unittest.main()
