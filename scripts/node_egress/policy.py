"""Compile node-local policies while preserving the original first-match rules."""

import hashlib
import ipaddress
import json
import re
import secrets
import socket


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


def domain(value):
    value = value.lower().rstrip(".").encode("idna").decode()
    if len(value) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
        for p in value.split(".")
    ):
        raise ValueError("Invalid domain in egress list")
    return value


def resolve_list(spec):
    selected = {domain(item) for item in spec.get("include_domains", [])}
    results = 0
    for suffix, sample in spec["domains"].items():
        suffix, sample = domain(suffix), domain(sample)
        if sample != suffix and not sample.endswith("." + suffix):
            raise ValueError("DNS sample is outside the configured suffix")
        try:
            answers = socket.getaddrinfo(
                sample, 443, socket.AF_INET6, socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            if exc.errno in (socket.EAI_NONAME, socket.EAI_NODATA):
                results += 1
                continue
            raise
        results += 1
        if any(ipaddress.ip_address(a[4][0]).is_global for a in answers):
            selected.add(suffix)
    if not results or not selected:
        raise ValueError("Empty DNS refresh")
    networks = [ipaddress.IPv6Network(n, strict=True) for n in spec["ipv6_networks"]]
    if any(not n.subnet_of(ipaddress.IPv6Network("2000::/3")) for n in networks):
        raise ValueError("Only public IPv6 prefixes can be selected")
    # An IPv4 literal has no universal IPv6 counterpart. Publish only
    # operator-declared aliases whose current A set contains the original IP.
    aliases = {}
    for address, hostname in spec.get("ipv4_aliases", {}).items():
        source = ipaddress.IPv4Address(address)
        if not source.is_global:
            raise ValueError("IPv4 aliases require a public source")
        hostname = domain(hostname)
        try:
            answers = socket.getaddrinfo(
                hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            if exc.errno in (socket.EAI_NONAME, socket.EAI_NODATA):
                continue
            raise
        ips = {ipaddress.ip_address(a[4][0]) for a in answers}
        if (
            source in ips
            and all(ip.is_global for ip in ips)
            and any(ip.version == 6 for ip in ips)
        ):
            aliases[str(source)] = hostname
    return {
        "ipv4_aliases": aliases,
        "domain": ["domain:" + s for s in sorted(selected)],
        "ip": sorted({str(n) for n in networks}),
    }


def render(base, inbounds, users, targets):
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
            ("-default", "ForceIPv4v6"),
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
        for hostname in sorted(set(targets.get("ipv4_aliases", {}).values())):
            alias_tag = hashlib.sha256(hostname.encode()).hexdigest()[:16]
            outs.append(
                {
                    "tag": tag + "-alias-" + alias_tag,
                    "protocol": "freedom",
                    "settings": {"redirect": hostname + ":0"},
                    "streamSettings": {
                        "sockopt": {
                            "mark": user["mark"],
                            "domainStrategy": "ForceIP",
                            "happyEyeballs": happy,
                        }
                    },
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
                    {
                        **common,
                        field: values,
                        "network": network,
                        "outboundTag": tag + suffix,
                    }
                    for field in ("domain", "ip")
                    if (values := targets.get(field))
                    for network, suffix in (("tcp", ""), ("udp", "-udp"))
                ]
                for address, hostname in sorted(
                    targets.get("ipv4_aliases", {}).items()
                ):
                    alias_tag = hashlib.sha256(hostname.encode()).hexdigest()[:16]
                    selected.append(
                        {
                            **common,
                            "ip": [address + "/32"],
                            "network": "tcp",
                            "outboundTag": tag + "-alias-" + alias_tag,
                        }
                    )
                # Unlisted domains prefer A. IPv6-only destinations still get the
                # assigned IPv6, never the interface's shared default address.
                selected.append({**common, "outboundTag": tag + "-default"})
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
