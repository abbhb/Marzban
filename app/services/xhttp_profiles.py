"""Public client-route metadata; never changes listeners or user permissions."""
from copy import deepcopy
from ipaddress import ip_address
import re

from app.subscription.xhttp import MAX_XHTTP_PROFILES, mihomo_xhttp_options

PROFILE_KEY = "x-marzban-xhttp-profiles"
TLS_FIELDS = {"serverName", "fingerprint", "alpn", "allowInsecure"}
REALITY_FIELDS = TLS_FIELDS | {"publicKey", "password", "shortId"}
XMUX_FIELDS = {"maxConcurrency", "maxConnections", "cMaxReuseTimes", "hMaxRequestTimes", "hMaxReusableSecs", "hKeepAlivePeriod"}
TRANSPORT_FIELDS = {"path", "host", "headers", "mode", "noGRPCHeader", "xPaddingBytes", "scMaxEachPostBytes", "scMinPostsIntervalMs", "xmux"}
CONNECTION_FIELDS = {"address", "port", "network", "security", "tlsSettings", "realitySettings", "xhttpSettings", "splithttpSettings"}


def _keys(value, allowed, field):
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"{field}: unsupported fields (server keys and certificates are not accepted)")


def _text(value, field, limit=256, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value) or (required and not value.strip()):
        raise ValueError(f"{field}: invalid text")
    return value


def _address(value):
    value = _text(value, "address", required=True).strip()
    try:
        return str(ip_address(value.removeprefix("[").removesuffix("]")))
    except ValueError:
        if len(value) > 253 or not re.fullmatch(r"[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\.?", value):
            raise ValueError("address: enter a hostname or an IPv4/IPv6 address without a port") from None
        return value


def _range(value, field):
    if type(value) is int and value >= 0:
        return
    if isinstance(value, str) and re.fullmatch(r"\d+(?:-\d+)?", value) and len(value) <= 24:
        numbers = [int(n) for n in value.split("-")]
        if numbers[0] <= numbers[-1]:
            return
    raise ValueError(f"{field}: enter a nonnegative integer or an ascending range")


def _transport(value, path, download=False):
    _keys(value, TRANSPORT_FIELDS | ({"extra", "downloadSettings"} if not download else set()), "xhttpSettings")
    if value.get("path", "") != path:
        raise ValueError("path: every route must use the existing backend path")
    for key in ("path", "host"):
        if key in value:
            _text(value[key], key, 1024)
    if value.get("mode", "auto") not in ("auto", "packet-up", "stream-up", "stream-one"):
        raise ValueError("mode: unsupported XHTTP mode")
    if "noGRPCHeader" in value and type(value["noGRPCHeader"]) is not bool:
        raise ValueError("noGRPCHeader: expected a boolean")
    headers = value.get("headers", {})
    if not isinstance(headers, dict) or len(headers) > 32:
        raise ValueError("headers: expected at most 32 headers")
    for name, content in headers.items():
        _text(name, "header name", 128, required=True)
        _text(content, "header value", 2048)
    for key in ("xPaddingBytes", "scMaxEachPostBytes", "scMinPostsIntervalMs"):
        if key in value:
            _range(value[key], key)
    xmux = value.get("xmux", {})
    _keys(xmux, XMUX_FIELDS, "xmux")
    for name, content in xmux.items():
        if name == "hKeepAlivePeriod":
            if type(content) is not int or content < 0:
                raise ValueError("hKeepAlivePeriod: expected a nonnegative integer")
        else:
            _range(content, name)
    if "extra" in value:
        extra = deepcopy(value["extra"])
        _keys(extra, TRANSPORT_FIELDS | {"downloadSettings"}, "extra")
        for key in ("path", "host", "mode"):
            extra[key] = value.get(key, "auto" if key == "mode" else "")
        _transport(extra, path)
    if value.get("downloadSettings"):
        _connection(value["downloadSettings"], path, download=True)


def _connection(value, path, download=False):
    _keys(value, CONNECTION_FIELDS, "connection")
    if value.get("network", "xhttp") not in ("xhttp", "splithttp"):
        raise ValueError("network: only XHTTP is supported")
    if "address" in value:
        value["address"] = _address(value["address"])
    if "port" in value and (type(value["port"]) is not int or not 1 <= value["port"] <= 65535):
        raise ValueError("port: enter an integer from 1 to 65535")
    security = value.get("security", "none")
    if security not in ("none", "tls", "reality"):
        raise ValueError("security: unsupported transport security")
    for key, fields in (("tlsSettings", TLS_FIELDS), ("realitySettings", REALITY_FIELDS)):
        tls = value.get(key, {})
        _keys(tls, fields, key)
        for name in fields - {"alpn", "allowInsecure"}:
            if name in tls:
                _text(tls[name], name, 512)
        if "alpn" in tls and (not isinstance(tls["alpn"], list) or not tls["alpn"] or any(a not in ("h2", "http/1.1", "h3") for a in tls["alpn"])):
            raise ValueError("alpn: expected h2, http/1.1 or h3")
        if "allowInsecure" in tls and type(tls["allowInsecure"]) is not bool:
            raise ValueError("allowInsecure: expected a boolean")
    if security != "none":
        _text(value.get(f"{security}Settings", {}).get("serverName", ""), "serverName", required=True)
    if security == "reality":
        tls = value.get("realitySettings", {})
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", tls.get("publicKey") or tls.get("password", "")):
            raise ValueError("publicKey: expected a REALITY public key")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,8}", tls.get("shortId", "")):
            raise ValueError("shortId: expected up to 16 hexadecimal characters in pairs")
    transport = value.get("xhttpSettings") or value.get("splithttpSettings") or {}
    _transport(transport, path, download=download)
    mihomo_xhttp_options(transport)


def validate_profiles(profiles, path):
    if not isinstance(profiles, list) or len(profiles) > MAX_XHTTP_PROFILES:
        raise ValueError(f"At most {MAX_XHTTP_PROFILES} profiles are allowed per inbound")
    profiles = deepcopy(profiles)
    labels = set()
    for index, profile in enumerate(profiles):
        try:
            _keys(profile, {"label", "enabled", "address", "port", "streamSettings"}, "profile")
            label = _text(profile.get("label"), "label", 150, required=True).strip()
            if label in labels:
                raise ValueError("label: profile names must be unique")
            labels.add(label)
            profile["label"] = label
            if type(profile.get("enabled", True)) is not bool:
                raise ValueError("enabled: expected a boolean")
            if profile.get("streamSettings") is not None:
                if "address" not in profile or "port" not in profile:
                    raise ValueError("address and port are required for a custom uplink")
                profile["address"] = _address(profile["address"])
                connection = {**profile["streamSettings"], "address": profile["address"], "port": profile["port"]}
                _connection(connection, path)
            elif "address" in profile or "port" in profile:
                raise ValueError("Custom addresses require streamSettings")
        except (ValueError, TypeError) as error:
            raise ValueError(f"Profile {index + 1}: {error}") from None
    return profiles


def _public_stream(stream, download=False):
    result = {key: deepcopy(value) for key, value in stream.items() if key in CONNECTION_FIELDS}
    for key, fields in (("tlsSettings", TLS_FIELDS), ("realitySettings", REALITY_FIELDS)):
        if key in result:
            result[key] = {name: value for name, value in result[key].items() if name in fields}
    for key in ("xhttpSettings", "splithttpSettings"):
        if key not in result:
            continue
        transport = result[key]
        allowed = TRANSPORT_FIELDS | ({"extra", "downloadSettings"} if not download else set())
        result[key] = {name: value for name, value in transport.items() if name in allowed}
        if "extra" in result[key]:
            result[key]["extra"] = {name: value for name, value in result[key]["extra"].items() if name in TRANSPORT_FIELDS | {"downloadSettings"}}
        for target in (result[key], result[key].get("extra", {})):
            if "xmux" in target:
                target["xmux"] = {name: value for name, value in target["xmux"].items() if name in XMUX_FIELDS}
            if target.get("downloadSettings"):
                target["downloadSettings"] = _public_stream(target["downloadSettings"], download=True)
    return result


def profile_document(config, hosts, revision):
    """Return only client parameters, not the surrounding core configuration."""
    inbounds = []
    for tag, inbound in config.inbounds_by_tag.items():
        if inbound["network"] not in ("xhttp", "splithttp"):
            continue
        rows = hosts.get(tag, [])
        host = next(iter(rows), {})
        security = host.get("tls") or inbound.get("tls", "none")
        stream = {"network": "xhttp", "security": security,
                  "xhttpSettings": deepcopy(inbound.get("xhttpSettings", {}))}
        tls = {"serverName": next(iter(host.get("sni") or []), inbound.get("sni", [""])[0] if inbound.get("sni") else ""),
               "fingerprint": host.get("fingerprint") or inbound.get("fp") or "chrome",
               "alpn": (host.get("alpn") or "h2").split(","),
               "allowInsecure": bool(host.get("allowinsecure") or inbound.get("ais", False))}
        if security == "reality":
            tls.update(publicKey=inbound.get("pbk", ""), shortId=next(iter(inbound.get("sids") or []), ""))
        if security in ("tls", "reality"):
            stream[f"{security}Settings"] = tls
        transport = stream["xhttpSettings"]
        transport["path"] = host.get("path") or inbound.get("path", "")
        if host.get("host"):
            transport["host"] = host["host"][0]
        # Never expose server-only TLS fields from inherited downlink defaults.
        stream = _public_stream(stream)
        default = {"address": next(iter(host.get("address") or []), ""),
                   "port": host.get("port") or inbound["port"], "streamSettings": stream}
        profiles = validate_profiles(inbound.get("xhttpProfiles", []), inbound.get("path", ""))
        inbounds.append({"tag": tag, "path": inbound.get("path", ""), "profiles": profiles, "defaults": default})
    return {"revision": revision, "limit": MAX_XHTTP_PROFILES, "inbounds": inbounds}
