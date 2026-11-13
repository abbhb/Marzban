"""Compile node-local policies while preserving the original first-match rules."""

import hashlib
import json
import secrets


def new_mark(prefix, occupied):
    maximum = 65535
    available = maximum - len(occupied)
    if not available:
        raise ValueError("Instance mark range is exhausted")
    if available < maximum // 2:
        return secrets.choice(
            [
                (prefix << 16) | n
                for n in range(1, maximum + 1)
                if ((prefix << 16) | n) not in occupied
            ]
        )
    while True:
        mark = (prefix << 16) | (1 + secrets.randbelow(maximum))
        if mark not in occupied:
            return mark


def render(base, inbounds, users, _legacy_targets=None):
    # Older launchers may still pass a fourth argument during an upgrade.
    # It is intentionally ignored: IP literals are never remapped.
    if base["routing"].get("script") or base["routing"].get("balancers"):
        raise ValueError(
            "Custom router scripts and balancers require explicit integration"
        )
    rules = base["routing"]["rules"]
    if any(r.get("ruleTag", "").startswith("mz6-") for r in rules):
        raise ValueError("Reserved egress rule tag in base config")
    # Insert only before the selected inbound's unconditional direct route or
    # the default. Earlier blocking, user-specific and tunnel routes keep priority.
    slots = {}
    for tag in inbounds:
        if base["inbounds"].get(tag) not in (
            "vless",
            "vmess",
            "trojan",
            "shadowsocks",
            "hysteria",
        ):
            raise ValueError(f"Missing managed inbound: {tag}")
        for index, rule in enumerate(rules):
            if set(rule) <= {"inboundTag", "type", "outboundTag", "ruleTag"} and (
                not rule.get("inboundTag") or tag in rule["inboundTag"]
            ):
                direct = rule.get("outboundTag")
                break
        else:
            index, direct = len(rules), base["default"]
        if direct not in base["direct"]:
            raise ValueError(f"{tag} does not have a plain direct exit")
        slots.setdefault(index, []).append(tag)
    final = []
    outs = []
    happy = {
        "tryDelayMs": 300,
        "prioritizeIPv6": True,
        "interleave": 1,
        "maxConcurrentTry": 4,
    }
    for user in users:
        # Mark both families. Only IPv6 is source-translated on the node.
        tag = f"mz6-{user['mark']:x}"
        for suffix, strategy in (
            ("", "ForceIP"),
            ("-udp", "ForceIPv6v4"),
        ):
            sockopt = {"mark": user["mark"], "domainStrategy": strategy}
            if not suffix:
                sockopt["happyEyeballs"] = happy
            outs.append(
                {
                    "tag": tag + suffix,
                    "protocol": "freedom",
                    "streamSettings": {"sockopt": sockopt},
                }
            )
    for idx in range(len(rules) + 1):
        if idx in slots:
            for user in users:
                tag = f"mz6-{user['mark']:x}"
                common = {
                    "type": "field",
                    "inboundTag": slots[idx],
                    "user": [user["email"]],
                }
                selected = [
                    {**common, "network": "tcp", "outboundTag": tag},
                    {**common, "network": "udp", "outboundTag": tag + "-udp"},
                ]
                for rule in selected:
                    rule["ruleTag"] = (
                        "mz6-"
                        + hashlib.sha256(
                            json.dumps(rule, sort_keys=True).encode()
                        ).hexdigest()[:24]
                    )
                    final.append(rule)
            # A user can appear through the node API before the next sync. Keep
            # that user off the shared IPv6 until its own source is ready.
            final.append(
                {
                    "type": "field",
                    "inboundTag": slots[idx],
                    "ruleTag": f"mz6-pending-{idx}",
                    "outboundTag": "mz6-pending",
                }
            )
        if idx < len(rules):
            final.append(rules[idx])
    if slots:
        outs.append({"tag": "mz6-pending", "protocol": "blackhole"})
    return final, outs
