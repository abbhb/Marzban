#!/usr/bin/env python3
"""Install a fail-closed source route for HY03's dedicated US01 tunnel."""
import json
import subprocess

SOURCE = "10.66.66.5"
DEVICE = "wg-us01"
TABLE = 14200
PRIORITY = 14200
NFT_TABLE = "hy03_us01"


def run(args, *, input_text=None, check=True):
    return subprocess.run(args, input=input_text, text=True, capture_output=True, check=check)


def ensure():
    # Refuse to take over another policy with the same rule priority or table.
    rules = json.loads(run(["ip", "-j", "-4", "rule", "show"]).stdout)
    existing = [rule for rule in rules if rule.get("priority") == PRIORITY]
    if existing and (len(existing) != 1
                     or existing[0].get("src") not in (SOURCE, SOURCE + "/32")
                     or str(existing[0].get("table")) != str(TABLE)):
        raise RuntimeError("Policy priority is already in use")
    query = run(["ip", "-j", "-4", "route", "show", "table", str(TABLE)], check=False)
    routes = json.loads(query.stdout) if query.returncode == 0 else []
    for route in routes:
        if (route.get("dst", "default") != "default" or
            not ((route.get("type") == "unreachable" and route.get("metric") == 32760)
                 or (route.get("dev") == DEVICE and route.get("metric") == 100))):
            raise RuntimeError("Policy routing table is already in use")

    existing_table = run(["nft", "list", "table", "ip", NFT_TABLE], check=False)
    if existing_table.returncode == 0:
        text = existing_table.stdout
        if not all(item in text for item in ("chain output", "hook output", SOURCE, DEVICE, "reject")):
            raise RuntimeError("Existing kill switch has unexpected contents")
    else:
        ruleset = f'''add table ip {NFT_TABLE}
add chain ip {NFT_TABLE} output {{ type filter hook output priority filter; policy accept; }}
add rule ip {NFT_TABLE} output ip saddr {SOURCE} oifname != "{DEVICE}" counter reject
'''
        run(["nft", "-f", "-"], input_text=ruleset)
    # Keep an unreachable route even when the interface or peer is down.
    run(["ip", "-4", "route", "replace", "unreachable", "default", "table", str(TABLE), "metric", "32760"])
    if not existing:
        run(["ip", "-4", "rule", "add", "priority", str(PRIORITY), "from", SOURCE + "/32", "lookup", str(TABLE)])


if __name__ == "__main__":
    ensure()
