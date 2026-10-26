"""Resolve flow exclusively from the inbound for startup, updates and exports."""

FLOW_KEY = "x-marzban-flow"
VISION = "xtls-rprx-vision"


def supports_vision(inbound):
    return (inbound.get("protocol") == "vless"
            and inbound.get("network", "tcp") in ("tcp", "raw", "kcp")
            and inbound.get("tls") in ("tls", "reality")
            and inbound.get("header_type") != "http")


def settings_for_inbound(settings, inbound):
    result = dict(settings)
    if inbound.get("protocol") != "vless":
        return result
    result["flow"] = inbound.get("flow_override") or ""
    if result.get("flow") and not supports_vision(inbound):
        result["flow"] = ""
    return result
