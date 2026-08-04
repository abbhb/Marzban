"""Shared compatibility policy for imported external Clash proxy nodes."""

import re


LEGACY_EXTERNAL_PROXY_TYPES = frozenset({
    "http",
    "snell",
    "socks5",
    "ss",
    "ssr",
    "trojan",
    "vmess",
})
MIHOMO_EXTERNAL_PROXY_TYPES = LEGACY_EXTERNAL_PROXY_TYPES | frozenset({
    "anytls",
    "hysteria",
    "hysteria2",
    "masque",
    "mieru",
    "ssh",
    "tuic",
    "vless",
    "wireguard",
})
EXTERNAL_PROXY_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
