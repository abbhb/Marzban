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
        for source, target in (("address", "server"), ("port", "port")):
            if source in download:
                down[target] = download[source]
        security = download.get("security", "none")
        if security not in ("none", "tls", "reality"):
            raise ValueError("Unsupported XHTTP downloadSettings security")
        down["tls"] = security != "none"
        # The download leg must not inherit an uplink REALITY configuration.
        down["reality-opts"] = {"public-key": ""}
        tls = download.get(f"{security}Settings") or {}
        down["servername"] = tls.get("serverName") or download.get("address", "")
        down["skip-cert-verify"] = bool(tls.get("allowInsecure", False))
        for source, target in (("fingerprint", "client-fingerprint"), ("alpn", "alpn")):
            if source in tls:
                down[target] = deepcopy(tls[source])
        if security == "none":
            down["alpn"] = ["http/1.1"]
        if security == "reality":
            down["reality-opts"] = {
                "public-key": tls.get("password") or tls.get("publicKey", ""),
                "short-id": tls.get("shortId", ""),
            }
        options["download-settings"] = down
    return options
