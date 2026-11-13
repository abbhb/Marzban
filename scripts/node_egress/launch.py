#!/usr/local/bin/python3
"""Marzban-node XRAY_EXECUTABLE_PATH entry point. Installed per instance."""

import json
import os
import sys
import tempfile
from pathlib import Path

from policy import render

HERE = Path(__file__).resolve().parent
XRAY = str(HERE.parent / "xray")
STATE = Path("/var/lib/marzban-node/egress")
CONTROL = "mz-egress-control"


def prepare(config):
    # The node has already filtered INBOUNDS and injected its existing TLS API.
    routing = config["routing"]
    if routing.get("script") or any(i["tag"] == CONTROL for i in config["inbounds"]):
        raise ValueError("Cannot add node egress control to this routing configuration")
    api = config["api"]
    if api.get("listen"):
        raise ValueError("Node must use the Marzban API outbound")
    api["services"] = list(dict.fromkeys([*api["services"], "RoutingService"]))
    config["inbounds"].append(
        {
            "tag": CONTROL,
            "listen": str(STATE / "control.sock"),
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        }
    )
    routing["rules"].insert(
        0, {"type": "field", "inboundTag": [CONTROL], "outboundTag": api["tag"]}
    )
    if any(o.get("tag", "").startswith("mz6-") for o in config["outbounds"]):
        raise ValueError("Reserved mz6- outbound tag in node configuration")
    direct = [
        o["tag"]
        for o in config["outbounds"]
        if o["protocol"] == "freedom"
        and not any(
            o.get(k)
            for k in ("sendThrough", "settings", "streamSettings", "proxySettings")
        )
    ]
    return {
        "default": config["outbounds"][0]["tag"],
        "direct": direct,
        "pid": os.getpid(),
        "routing": routing,
        "inbounds": {i["tag"]: i["protocol"] for i in config["inbounds"]},
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["run", "-config", "stdin:"]:
        os.umask(0o077)
        STATE.mkdir(mode=0o700, exist_ok=True)
        config = json.load(sys.stdin)
        snapshot = prepare(config)
        with tempfile.NamedTemporaryFile(dir=STATE, mode="w", delete=False) as f:
            json.dump(snapshot, f)
        os.replace(f.name, STATE / "base.json")
        guard = STATE / "managed-inbounds.json"
        if guard.exists():
            rules, pending = render(snapshot, json.loads(guard.read_text()), [])
            config["routing"]["rules"] = rules
            config["outbounds"].extend(pending)
        # Unlinked file is inherited as stdin, no credentials written to a named file.
        with tempfile.TemporaryFile() as f:
            f.write(json.dumps(config).encode())
            f.seek(0)
            os.dup2(f.fileno(), 0)
        (STATE / "control.sock").unlink(missing_ok=True)
    os.execv(XRAY, [XRAY, *sys.argv[1:]])
