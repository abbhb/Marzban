"""Opt-in Mihomo DNS defaults, applied after subscription authorization."""

from urllib.parse import urlsplit


BOOTSTRAP_DOH = (
    "https://223.5.5.5/dns-query#DIRECT",
    "https://223.6.6.6/dns-query#DIRECT",
)
PUBLIC_DOH = ("https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query")

# These exceptions require real answers, not a different resolver or outbound.
# Keep ordinary websites out of this list: broad service suffixes unnecessarily
# replace fake-IP mappings with upstream lookups for unrelated application traffic.
LOCAL_FAKE_IP_EXCEPTIONS = (
    "+.lan", "+.local", "+.localhost", "+.internal", "+.localdomain",
    "+.home.arpa", "WORKGROUP",
)
TIME_FAKE_IP_EXCEPTIONS = (
    "time.*.com", "time.*.gov", "time.*.edu.cn", "time.*.apple.com",
    "time-ios.apple.com", "ntp.*.com", "*.time.edu.cn", "*.ntp.org.cn",
    "+.pool.ntp.org",
    *(f"time{number}.*.com" for number in range(1, 8)),
    *(f"ntp{number}.*.com" for number in range(1, 8)),
)
STUN_FAKE_IP_EXCEPTIONS = (
    "+.stun.*.*", "+.stun.*.*.*", "+.stun.*.*.*.*", "+.stun.*.*.*.*.*",
    "+.stun.playstation.net",
)
CONNECTIVITY_FAKE_IP_EXCEPTIONS = (
    "+.msftconnecttest.com", "+.msftncsi.com",
    "localhost.ptlogin2.qq.com", "localhost.sec.qq.com",
)


def _proxy_only(document: dict, name: str, active: frozenset = frozenset()) -> bool:
    """Every selectable path must terminate in a proxy or rejection."""
    if name in {"REJECT", "REJECT-DROP"}:
        return True
    if name in {"DIRECT", "PASS", "COMPATIBLE", "GLOBAL"} or name in active:
        return False
    for node in document.get("proxies", []):
        if node.get("name") == name:
            return bool(node.get("server")) and node.get("type", "").lower() not in {
                "direct", "dns", "reject", "pass", "compatible",
            }
    for group in document.get("proxy-groups", []):
        if group.get("name") == name:
            # Provider/filter expansion is deliberately not assumed safe here.
            if any(group.get(key) for key in ("use", "include-all", "include-all-proxies", "include-all-providers")):
                return False
            members = group.get("proxies", [])
            return bool(members) and all(
                _proxy_only(document, member, active | {name}) for member in members
            )
    return False


def secure_mihomo_dns(document: dict, primary_group: str, subscription_url: str) -> None:
    """Use only the authorized proxy selector; no plaintext/system fallback.

    Node-hostname bootstrap is the sole general direct-DNS exception. The panel
    hostname also resolves directly so subscription retrieval works independently
    of proxy availability. Client-owned VPN policies are merged by the client.
    """
    outbound = primary_group if _proxy_only(document, primary_group) else "REJECT"
    direct_domains = {}
    panel_host = urlsplit(subscription_url).hostname
    if panel_host:
        direct_domains[panel_host] = list(BOOTSTRAP_DOH)
    document["dns"] = {
        "enable": True,
        "listen": "127.0.0.1:1053",
        "ipv6": False,
        "enhanced-mode": "fake-ip",
        "fake-ip-range": "198.18.0.1/16",
        "fake-ip-filter-mode": "blacklist",
        "fake-ip-filter": [
            *LOCAL_FAKE_IP_EXCEPTIONS,
            *TIME_FAKE_IP_EXCEPTIONS,
            *STUN_FAKE_IP_EXCEPTIONS,
            *CONNECTIVITY_FAKE_IP_EXCEPTIONS,
        ],
        "use-hosts": True,
        "prefer-h3": False,
        "respect-rules": True,
        "default-nameserver": list(BOOTSTRAP_DOH),
        "proxy-server-nameserver": list(BOOTSTRAP_DOH),
        "nameserver": [f"{server}#{outbound}" for server in PUBLIC_DOH],
        "nameserver-policy": direct_domains,
        # Even a DIRECT application connection resolves through the encrypted
        # proxy resolvers. UniVPN can override individual private DNS policies.
        "direct-nameserver": [],
        "direct-nameserver-follow-policy": True,
        "fallback": [],
    }
    document["clash-for-android"] = {"append-system-dns": False}
    # The client owns enable/disable. Do not activate TUN from a subscription.
    document["tun"] = {
        "auto-route": True,
        "auto-detect-interface": True,
        "strict-route": True,
        "dns-hijack": ["any:53", "tcp://any:53"],
        "inet6-address": ["fdfe:dcba:9876::1/126"],
    }
    # Capture literal IPv6 traffic when the client enables TUN, independently
    # of the conservative AAAA-answer policy above and the node's IP family.
    document["ipv6"] = True
