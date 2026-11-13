"""Bounded, read-only connection observations from an individual Xray core.

Only the host observer's successful socket events establish an egress family.
Access logs describe requests and must never be used to guess DNS results.
"""

import ipaddress
import json
import re
from collections import deque
from datetime import datetime, timezone

MARKER = "MZCONN "
MAX_RECORDS = 500
MAX_LINE = 16384
ACCESS = re.compile(
    r"from (?P<source>\S+) accepted (?P<network>tcp|udp):(?P<target>\S+)"
    r"(?: \[(?P<route>[^\]]+)\])?(?: email: (?P<user>\S+))?"
)


def endpoint(value):
    """Return a numeric address/family, including mapped IPv4 and zone IDs."""
    value = re.sub(r"^(tcp|udp):", "", value)
    if value.startswith("["):
        host = value[1:].split("]", 1)[0]
    elif value.count(":") == 1:
        host = value.rsplit(":", 1)[0]
    else:
        host = value
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_unspecified:
            return None, None
        return str(address), f"IPv{address.version}"
    except ValueError:
        return None, None


def username(identity):
    return re.sub(r"^\d+\.", "", identity, count=1)


class ConnectionObservations:
    def __init__(self, limit=MAX_RECORDS):
        self.records = deque(maxlen=limit)
        self.observer = False
        self.sequence = 0

    def feed(self, text):
        changed = False
        for line in text.splitlines():
            if len(line) > MAX_LINE:
                continue
            if line.startswith(MARKER):
                try:
                    event = json.loads(line[len(MARKER):])
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict) or event.get("version") != 1:
                    continue
                if event.get("event") == "ready":
                    self.observer = True
                    changed = True
                    continue
                if event.get("event") != "dial" or not all(
                    isinstance(event.get(key), str) and len(event[key]) <= 1024
                    for key in ("id", "timestamp", "user", "source", "target", "network",
                                "inbound", "outbound", "local", "remote")
                ):
                    continue
                # Xray's protobuf Network.String() emits uppercase TCP/UDP.
                network = event["network"].lower()
                if not event["user"] or network not in ("tcp", "udp"):
                    continue
                remote_ip, remote_family = endpoint(event["remote"])
                # Ignore virtual pipe connections; the physical dial has its own event.
                if not remote_ip:
                    continue
                self.observer = True
                source_ip, source_family = endpoint(event["source"])
                local_ip, _ = endpoint(event["local"])
                record = {
                    "id": event["id"], "timestamp": event["timestamp"],
                    "user": username(event["user"]), "identity": event["user"],
                    "source": event["source"], "source_ip": source_ip,
                    "source_family": source_family, "target": event["target"],
                    "network": network, "inbound": event["inbound"],
                    "outbound": event["outbound"], "local": event["local"],
                    "local_ip": local_ip, "remote": event["remote"],
                    "remote_ip": remote_ip, "egress_family": remote_family,
                    "evidence": "socket", "status": "opened",
                }
                # Upgrade a matching pending request; identity and the complete
                # source/target tuple come from the same authenticated context.
                # Unobserved tunnel/multiplexed requests remain visibly unknown.
                for pending in reversed(self.records):
                    if pending["evidence"] == "access_log" and self._key(pending) == self._key(record):
                        self.records.remove(pending)
                        break
            else:
                match = ACCESS.search(line)
                if not match or not match["user"]:
                    continue
                self.sequence += 1
                source_ip, source_family = endpoint(match["source"])
                route = re.split(r"\s+(?:->|>>|==>)\s+", match["route"] or "")
                record = {
                    "id": f"request-{self.sequence}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user": username(match["user"]), "identity": match["user"],
                    "source": match["source"], "source_ip": source_ip,
                    "source_family": source_family, "target": match["target"],
                    "network": match["network"],
                    "inbound": route[0] if len(route) > 1 else "",
                    "outbound": route[-1], "local": "", "local_ip": None,
                    "remote": "", "remote_ip": None, "egress_family": None,
                    "evidence": "access_log", "status": "requested",
                }
            self.records.appendleft(record)
            changed = True
        return changed

    def snapshot(self):
        return {"type": "snapshot", "observer": self.observer,
                "limit": self.records.maxlen, "records": list(self.records)}

    @staticmethod
    def _key(record):
        return (record["identity"], record["source"].removeprefix("tcp:").removeprefix("udp:"),
                record["target"].removeprefix("tcp:").removeprefix("udp:"),
                record["network"], record["inbound"], record["outbound"])
