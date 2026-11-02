"""Materialize cascade dependencies without adding them to policy choices."""
from copy import deepcopy
import hashlib
import json
import re


def entry_key(node: dict) -> str:
    canonical = json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "MGMA-HOP · " + hashlib.sha256(canonical.encode()).hexdigest()[:20]


def apply_cascades(document: dict, entries: dict[str, dict]) -> dict:
    proxies = document.setdefault("proxies", [])
    groups = document.get("proxy-groups", [])
    used = {item["name"] for item in [*proxies, *groups] if isinstance(item, dict) and "name" in item}
    used.update({"DIRECT", "REJECT", "GLOBAL", "PASS", "COMPATIBLE", "REJECT-DROP"})
    helper_names = []
    for key, payload in entries.items():
        landings = [node for node in proxies if node.get("dialer-proxy") == key]
        if not landings:
            continue
        name = key
        while name in used:
            name += "_"
        used.add(name)
        helper_names.append(name)
        entry = deepcopy(payload)
        entry["name"] = name
        proxies.append(entry)
        for node in landings:
            node["dialer-proxy"] = name
    if helper_names:
        pattern = "^(?:" + "|".join(re.escape(name) for name in helper_names) + ")$"
        for group in groups:
            if group.get("include-all") or group.get("include-all-proxies"):
                previous = group.get("exclude-filter")
                group["exclude-filter"] = f"(?:{previous})|(?:{pattern})" if previous else pattern
    return document
