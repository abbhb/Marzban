#!/usr/local/bin/python3
"""Run the dedicated HY03 ingress with a fail-closed US01 WireGuard exit."""
import json
import os
import sys
import tempfile

INBOUND = "US03_HY2_WG_US01"
DNS_TAG = "hy03-us01-wg-dns"
EGRESS = "hy03-us01-wg-egress"
DENY = "hy03-us01-default-deny"
SOURCE = "10.66.66.5"
XRAY = "/opt/xray/xray"


def prepare(config):
    """Modify only the filtered Xray configuration for this one node."""
    inbounds = config.get("inbounds", [])
    selected = [item for item in inbounds if item.get("tag") == INBOUND]
    if len(selected) != 1 or selected[0].get("protocol") != "hysteria":
        raise ValueError("The dedicated Hysteria inbound is missing")
    if any(item.get("tag") == DNS_TAG for item in inbounds):
        raise ValueError("Reserved DNS tag is already in use")

    outbounds = config.get("outbounds", [])
    tags = {item.get("tag") for item in outbounds}
    if not outbounds or tags & {EGRESS, DENY}:
        raise ValueError("Reserved WireGuard outbound tags are in use")

    routing = config.setdefault("routing", {})
    if routing.get("script") or routing.get("balancers"):
        raise ValueError("Router scripts and balancers require explicit review")
    rules = routing.setdefault("rules", [])
    protocols = {outbound.get("tag"): outbound.get("protocol") for outbound in outbounds}
    for rule in rules:
        incoming = rule.get("inboundTag")
        applies = not incoming or INBOUND in incoming or DNS_TAG in incoming
        if applies and protocols.get(rule.get("outboundTag")) != "blackhole":
            raise ValueError("Existing route could bypass the WireGuard exit")

    # Fail closed if a future routing change misses an inbound. Existing
    # explicit blocking rules retain their order and continue to apply.
    outbounds.insert(0, {"tag": DENY, "protocol": "blackhole"})
    outbounds.append({
        "tag": EGRESS,
        "protocol": "freedom",
        "sendThrough": SOURCE,
        "streamSettings": {"sockopt": {"domainStrategy": "ForceIPv4"}},
    })
    # The two resolver IPs are literals; DNS requests themselves use the
    # same source-bound outbound and therefore cannot escape through US03.
    config["dns"] = {
        "tag": DNS_TAG,
        "queryStrategy": "UseIPv4",
        "servers": ["1.1.1.1", "8.8.8.8"],
    }
    rules.append({
        "type": "field",
        "inboundTag": [INBOUND, DNS_TAG],
        "outboundTag": EGRESS,
    })
    return config


if __name__ == "__main__":
    if sys.argv[1:] == ["run", "-config", "stdin:"]:
        config = prepare(json.load(sys.stdin))
        # Credentials and inline TLS material never enter a named file.
        with tempfile.TemporaryFile() as f:
            f.write(json.dumps(config).encode())
            f.seek(0)
            os.dup2(f.fileno(), 0)
    os.execv(XRAY, [XRAY, *sys.argv[1:]])
