"""Translate Xray XHTTP client settings to Mihomo's transport options."""

from copy import deepcopy


_TRANSPORT_FIELDS = {
    "path": "path",
    "host": "host",
    "headers": "headers",
    "mode": "mode",
    "noGRPCHeader": "no-grpc-header",
    "xPaddingBytes": "x-padding-bytes",
    "scMaxEachPostBytes": "sc-max-each-post-bytes",
    "scMinPostsIntervalMs": "sc-min-posts-interval-ms",
}
_XMUX_FIELDS = {
    "maxConcurrency": "max-concurrency",
    "maxConnections": "max-connections",
    "cMaxReuseTimes": "c-max-reuse-times",
    "hMaxRequestTimes": "h-max-request-times",
    "hMaxReusableSecs": "h-max-reusable-secs",
    "hKeepAlivePeriod": "h-keep-alive-period",
}


def _effective(settings):
    if settings.get("extra") is None:
        return deepcopy(settings)
    # Xray replaces the transport with extra, retaining only these outer fields.
    result = deepcopy(settings["extra"])
    for key in ("host", "path", "mode"):
        result[key] = settings.get(key, "")
    result["mode"] = result["mode"] or "auto"
    return result


def _reuse(settings):
    return {
        target: value if source == "hKeepAlivePeriod" else str(value)
        for source, target in _XMUX_FIELDS.items()
        if (value := settings.get(source)) is not None
    }


def _connection_options(settings):
    options = {}
    for source, target in (("address", "server"), ("port", "port")):
        if source in settings:
            options[target] = settings[source]
    security = settings.get("security", "none")
    if security not in ("none", "tls", "reality"):
        raise ValueError("Unsupported XHTTP connection security")
    options["tls"] = security != "none"
    options["reality-opts"] = {"public-key": ""}
    tls = settings.get(f"{security}Settings") or {}
    options["servername"] = tls.get("serverName") or settings.get("address", "")
    options["skip-cert-verify"] = bool(tls.get("allowInsecure", False))
    options["client-fingerprint"] = tls.get("fingerprint", "chrome")
    options["alpn"] = tls.get("alpn", ["h2"] if security != "none" else ["http/1.1"])
    if security == "reality":
        options["reality-opts"] = {
            "public-key": tls.get("password") or tls.get("publicKey", ""),
            "short-id": tls.get("shortId", ""),
            "support-x25519mlkem768": True,
        }
    return deepcopy(options)


def mihomo_xhttp_options(settings):
    settings = _effective(settings)
    options = {
        target: deepcopy(settings[source])
        for source, target in _TRANSPORT_FIELDS.items()
        if source in settings
    }
    for key in ("sc-max-each-post-bytes", "sc-min-posts-interval-ms"):
        if key in options:
            options[key] = str(options[key])
    if settings.get("xmux"):
        options["reuse-settings"] = _reuse(settings["xmux"])

    download = settings.get("downloadSettings")
    if download:
        if download.get("network", "xhttp") not in ("xhttp", "splithttp"):
            raise ValueError("XHTTP downloadSettings must use the xhttp transport")
        transport = _effective(download.get("xhttpSettings") or download.get("splithttpSettings") or {})
        # Mihomo's download-settings supports only these transport overrides.
        down = {key: deepcopy(transport[key]) for key in ("path", "host", "headers") if key in transport}
        if transport.get("xmux"):
            down["reuse-settings"] = _reuse(transport["xmux"])
        # The download leg must not inherit an uplink REALITY configuration.
        down.update(_connection_options(download))
        # Mihomo otherwise inherits the uplink Host, which breaks a CDN leg
        # paired with a different REALITY SNI/authority.
        down["host"] = transport.get("host") or down["servername"] or down.get("server", "")
        options["download-settings"] = down
    return options


def mihomo_xhttp_profiles(base, profiles):
    """Export named client routes to one authorized XHTTP backend.

    Only transport fields are accepted. Credentials always come from the user
    and server-side key/certificate material never reaches the subscription.
    """
    if profiles is None or profiles == []:
        return [base]
    if not isinstance(profiles, list) or len(profiles) > 8:
        raise ValueError("XHTTP profiles must be a list of at most eight items")
    nodes = []
    labels = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("Invalid XHTTP profile")
        label = profile.get("label")
        if not isinstance(label, str) or not label.strip() or label in labels:
            raise ValueError("XHTTP profiles require distinct nonempty labels")
        labels.add(label)
        node = deepcopy(base)
        node["name"] = f"{base['name']} · {label}"
        if (stream := profile.get("streamSettings")) is not None:
            if not isinstance(stream, dict):
                raise ValueError("Invalid XHTTP profile stream settings")
            if stream.get("network") not in ("xhttp", "splithttp"):
                raise ValueError("XHTTP profiles must use the xhttp transport")
            connection = dict(stream)
            connection["address"] = profile.get("address", base["server"])
            connection["port"] = profile.get("port", base["port"])
            if not isinstance(connection["address"], str) or not connection["address"]:
                raise ValueError("XHTTP profiles require an address")
            if type(connection["port"]) is not int or not 1 <= connection["port"] <= 65535:
                raise ValueError("Invalid XHTTP profile port")
            node.update(_connection_options(connection))
            transport = stream.get("xhttpSettings") or stream.get("splithttpSettings") or {}
            if transport.get("path") != base["xhttp-opts"].get("path"):
                raise ValueError("XHTTP profiles must reach the same backend path")
            node["xhttp-opts"] = mihomo_xhttp_options(transport)
        nodes.append(node)
    return nodes
