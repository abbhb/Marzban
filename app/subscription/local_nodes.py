"""Credential-free identities for the concrete routes of a local inbound."""
from copy import deepcopy
import hashlib
from ipaddress import ip_address
import json


def route_id(host, profile=None, inbound=None):
    # Names and enabled flags may change without granting a different route.
    endpoint = {key: value for key, value in host.items() if key != "remark"}
    transport = {key: value for key, value in (profile or {}).items()
                 if key not in {"label", "enabled"}}
    defaults = {key: (inbound or {}).get(key) for key in (
        "network", "tls", "port", "path", "sni", "host", "fp", "alpn",
        "pbk", "sids", "header_type", "xhttpSettings", "flow_override",
    )}
    encoded = json.dumps([endpoint, transport, defaults], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def route_uses_ipv6(host, profile=None, inbound=None):
    profile = profile or {}
    addresses = [profile["address"]] if profile.get("address") else host.get("address", [])
    stream = profile.get("streamSettings") or {}
    transport = (stream.get("xhttpSettings") or stream.get("splithttpSettings")
                 or (inbound or {}).get("xhttpSettings") or {})
    effective = transport["extra"] if isinstance(transport.get("extra"), dict) else transport
    download = effective.get("downloadSettings") or {}
    for address in [*addresses, download.get("address", "")]:
        try:
            if ip_address(address.strip("[]")).version == 6:
                return True
        except ValueError:
            pass
    return False


def selected_route(host, inbound, allowed):
    """None denies the host; an empty profile set must never mean 'all'."""
    if allowed is None:
        return deepcopy(inbound)
    result = deepcopy(inbound)
    profiles = inbound.get("xhttpProfiles") if inbound.get("network") in ("xhttp", "splithttp") else None
    if profiles:
        selected = [profile for profile in profiles if route_id(host, profile, inbound) in allowed]
        if not selected:
            return None
        result["xhttpProfiles"] = selected
    elif route_id(host, inbound=inbound) not in allowed:
        return None
    return result
