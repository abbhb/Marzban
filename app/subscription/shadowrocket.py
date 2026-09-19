"""Materialize authorized Clash policy groups for Shadowrocket YAML import.

Shadowrocket imports Clash YAML natively, including protocol-specific options.
Keep node dictionaries intact and resolve Mihomo include-all-proxies filters
server-side so imported policy groups do not silently lose their members.
"""

import copy
import re


class ShadowrocketConversionError(ValueError):
    """Credential-free export error safe to return to the client."""


def prepare_shadowrocket(document: dict) -> dict:
    if not isinstance(document, dict):
        raise ShadowrocketConversionError("Invalid subscription configuration")
    result = copy.deepcopy(document)
    nodes = result.get("proxies", [])
    groups = result.get("proxy-groups", [])
    if not isinstance(nodes, list) or not isinstance(groups, list):
        raise ShadowrocketConversionError("Invalid subscription nodes or groups")
    if result.get("proxy-providers"):
        raise ShadowrocketConversionError("Remote proxy providers must be materialized before Shadowrocket export")
    try:
        node_names = [n["name"] for n in nodes]
        group_names = [g["name"] for g in groups]
        names = node_names + group_names
        if any(not isinstance(n, str) or not n.strip() for n in names):
            raise ShadowrocketConversionError("Invalid subscription policy name")
        if len(names) != len(set(names)):
            raise ShadowrocketConversionError("Duplicate subscription policy names")
        known = set(names) | {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE", "GLOBAL"}
        references = {}
        for group in groups:
            if group.get("use") or group.get("include-all-providers"):
                raise ShadowrocketConversionError("Remote proxy providers must be materialized before Shadowrocket export")
            members = group.get("proxies", [])
            if not isinstance(members, list):
                raise ShadowrocketConversionError("Invalid subscription group members")
            members = list(members)
            if group.get("include-all-proxies") or group.get("include-all"):
                include = re.compile(group.get("filter") or ".*")
                exclude = re.compile(group["exclude-filter"]) if group.get("exclude-filter") else None
                excluded_types = set(str(group.get("exclude-type", "")).lower().split("|"))
                members.extend(n["name"] for n in nodes if include.search(n["name"])
                               and not (exclude and exclude.search(n["name"]))
                               and n["type"].lower() not in excluded_types)
            members = list(dict.fromkeys(members)) or ["REJECT"]
            if any(m not in known or m == group["name"] for m in members):
                raise ShadowrocketConversionError("Unresolved subscription policy reference")
            group["proxies"] = members
            # These now describe the explicit list above; applying them again
            # in a different client could filter out a group's fallback policy.
            for key in ("include-all", "include-all-proxies", "include-all-providers",
                        "filter", "exclude-filter", "exclude-type", "use"):
                group.pop(key, None)
            references[group["name"]] = [m for m in members if m in group_names]
        visited, active = set(), set()

        def visit(name):
            if name in active:
                raise ShadowrocketConversionError("Cyclic subscription policy groups")
            if name in visited:
                return
            active.add(name)
            for child in references.get(name, []):
                visit(child)
            active.remove(name)
            visited.add(name)

        for name in references:
            visit(name)
    except (KeyError, TypeError, re.error, RecursionError) as exc:
        raise ShadowrocketConversionError("Invalid Shadowrocket policy configuration") from exc
    return result
