"""Plan selection catalog; it contains neither user credentials nor core keys."""
from app import xray
from app.subscription.local_nodes import route_id, route_uses_ipv6


def node_catalog():
    result = []
    for tag, inbound in xray.config.inbounds_by_tag.items():
        if inbound.get("protocol") != "vless":
            continue
        nodes = []
        profiles = (inbound.get("xhttpProfiles") if inbound.get("network") in ("xhttp", "splithttp") else None) or [None]
        for host in xray.hosts.get(tag, []):
            for profile in profiles:
                ipv6 = route_uses_ipv6(host, profile, inbound)
                name = host.get("remark") or tag
                if profile:
                    name += " · " + profile["label"]
                if ipv6 and not name.startswith("[ipv6] "):
                    name = "[ipv6] " + name
                nodes.append({"id": route_id(host, profile, inbound), "name": name,
                              "ipv6": ipv6, "enabled": (profile or {}).get("enabled", True)})
        # Identical host definitions represent the same route.
        nodes = list({node["id"]: node for node in nodes}.values())
        result.append({"tag": tag, "nodes": sorted(nodes, key=lambda node: not node["ipv6"])})
    return result


def validate_selections(selections, inbound_tags):
    if set(selections) - set(inbound_tags):
        raise ValueError("Local node selections must belong to the plan's allowed inbounds")
    if not selections:
        return
    catalog = {item["tag"]: {node["id"] for node in item["nodes"]} for item in node_catalog()}
    for tag, selected in selections.items():
        if not selected or set(selected) - catalog.get(tag, set()):
            raise ValueError("Selected local routes are unavailable; reload and select the current routes")
