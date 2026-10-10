import copy
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from random import choice
from typing import Any
from uuid import UUID

import yaml
from jinja2.exceptions import TemplateNotFound

from app.subscription.funcs import get_grpc_gun
from app.subscription.external_policy import (
    EXTERNAL_PROXY_TYPE_RE,
    LEGACY_EXTERNAL_PROXY_TYPES,
    MIHOMO_EXTERNAL_PROXY_TYPES,
)
from app.templates import render_template
from app.utils.helpers import yml_uuid_representer
from config import (
    CLASH_SETTINGS_TEMPLATE,
    CLASH_SUBSCRIPTION_TEMPLATE,
    MUX_TEMPLATE,
    USER_AGENT_TEMPLATE,
)


EXTERNAL_AGGREGATE_GROUP_NAME = "MGMA · External"
EXTERNAL_NODE_NAME_PREFIX = "MGMA-EXT · "
EXTERNAL_NODE_EXCLUDE_PATTERN = r"^MGMA-EXT · "
PRIMARY_PROXY_GROUP_NAME = "🚀 节点选择"

CLASH_RESERVED_PROXY_NAMES = frozenset({
    "COMPATIBLE",
    "DIRECT",
    "GLOBAL",
    "PASS",
    "REJECT",
    "REJECT-DROP",
})

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]+")
_MAX_EXTERNAL_NAME_LENGTH = 200
_MAX_EXTERNAL_STRING_LENGTH = 65536
_MAX_EXTERNAL_COLLECTION_LENGTH = 2048
_MAX_EXTERNAL_VALUE_DEPTH = 12
_MAX_EXTERNAL_NODE_BYTES = 262144


def _clean_external_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize("NFKC", value)
    value = "".join(
        " " if unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} else char
        for char in value
    )
    value = " ".join(_CONTROL_CHAR_RE.sub(" ", value).split()).strip()
    if not value:
        return None
    return value[:_MAX_EXTERNAL_NAME_LENGTH].rstrip()


def _is_safe_external_value(value: Any, *, depth: int = 0) -> bool:
    """Accept only bounded JSON-like values in a materialized proxy node."""

    if depth > _MAX_EXTERNAL_VALUE_DEPTH:
        return False
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= _MAX_EXTERNAL_STRING_LENGTH
    if isinstance(value, list):
        return (
            len(value) <= _MAX_EXTERNAL_COLLECTION_LENGTH
            and all(_is_safe_external_value(item, depth=depth + 1) for item in value)
        )
    if isinstance(value, dict):
        return (
            len(value) <= _MAX_EXTERNAL_COLLECTION_LENGTH
            and all(
                isinstance(key, str)
                and len(key) <= 256
                and _is_safe_external_value(item, depth=depth + 1)
                for key, item in value.items()
            )
        )
    return False


def _canonical_external_node(node: dict) -> str | None:
    try:
        value = json.dumps(
            node,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None
    if len(value.encode("utf-8")) > _MAX_EXTERNAL_NODE_BYTES:
        return None
    return value


def _sanitize_external_node(raw_node: Any, *, is_meta: bool) -> tuple[dict, str] | None:
    if not isinstance(raw_node, dict) or not _is_safe_external_value(raw_node):
        return None
    # Upstream group/provider definitions are intentionally never imported.
    # A node that depends on one of those names would therefore be dangling or
    # could unexpectedly chain through a local group with the same name.
    if "dialer-proxy" in raw_node:
        return None

    original_name = _clean_external_name(raw_node.get("name"))
    raw_type = raw_node.get("type")
    server = raw_node.get("server")
    port = raw_node.get("port")
    if (
        original_name is None
        or not isinstance(raw_type, str)
        or not isinstance(server, str)
        or not server.strip()
    ):
        return None

    proxy_type = raw_type.strip().lower()
    if (
        not EXTERNAL_PROXY_TYPE_RE.fullmatch(proxy_type)
        or proxy_type not in MIHOMO_EXTERNAL_PROXY_TYPES
    ):
        return None
    if not is_meta and proxy_type not in LEGACY_EXTERNAL_PROXY_TYPES:
        return None

    if isinstance(port, str) and port.isascii() and port.isdigit():
        port = int(port)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None

    node = copy.deepcopy(raw_node)
    node["name"] = original_name
    node["type"] = proxy_type
    node["server"] = server.strip()
    node["port"] = port
    canonical = _canonical_external_node(node)
    if canonical is None:
        return None
    return node, canonical


def _truncate_external_name(base: str, suffix: str) -> str:
    available = max(1, _MAX_EXTERNAL_NAME_LENGTH - len(suffix))
    return f"{base[:available].rstrip()}{suffix}"


def _allocate_stable_name(base: str, used_names: set[str], stable_key: str) -> str:
    """Allocate a deterministic name without depending on overlay ordering."""

    digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
    for length in (8, 12, 16, 24, 32, 64):
        suffix = f" [{digest[:length]}]"
        candidate = _truncate_external_name(base, suffix)
        if candidate not in used_names:
            return candidate

    # A custom template would have to reserve every digest-width candidate to
    # reach this path.  The counter remains deterministic for that document.
    counter = 2
    while True:
        suffix = f" [{digest}-{counter}]"
        candidate = _truncate_external_name(base, suffix)
        if candidate not in used_names:
            return candidate
        counter += 1


def _document_names(proxies: list, proxy_groups: list) -> set[str]:
    names: set[str] = set()
    for item in [*proxies, *proxy_groups]:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _isolate_external_nodes_from_template_groups(proxy_groups: list) -> None:
    """Keep template-wide filters from implicitly capturing external nodes."""

    for group in proxy_groups:
        if not isinstance(group, dict) or group.get("include-all-proxies") is not True:
            continue
        current_filter = group.get("exclude-filter")
        if not isinstance(current_filter, str) or not current_filter.strip():
            group["exclude-filter"] = EXTERNAL_NODE_EXCLUDE_PATTERN
        elif EXTERNAL_NODE_EXCLUDE_PATTERN not in current_filter:
            # Keep a leading inline flag such as ``(?i)`` at the beginning of
            # the complete RE2 expression. Wrapping an existing filter would
            # move that flag into a nested group and can make Mihomo reject an
            # otherwise valid template filter.
            group["exclude-filter"] = (
                f"{current_filter}|{EXTERNAL_NODE_EXCLUDE_PATTERN}"
            )


def merge_clash_overlay(
    document: dict,
    clash_overlay: dict | None,
    *,
    is_meta: bool,
) -> dict:
    """Purely merge cached external proxy nodes into one rendered Clash config.

    Only ``sources[*].nodes`` is consumed.  No rules, groups, providers, DNS,
    or other top-level upstream configuration can cross this boundary.
    """

    result = copy.deepcopy(document)
    if not isinstance(result, dict) or not isinstance(clash_overlay, dict):
        return result

    raw_sources = clash_overlay.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        return result

    proxies = result.setdefault("proxies", [])
    proxy_groups = result.setdefault("proxy-groups", [])
    if not isinstance(proxies, list) or not isinstance(proxy_groups, list):
        return result

    prepared_sources: list[dict] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            continue
        source_id = raw_source.get("id")
        group_name = _clean_external_name(raw_source.get("group_name"))
        raw_nodes = raw_source.get("nodes")
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or group_name is None
            or not isinstance(raw_nodes, list)
        ):
            continue

        nodes: list[tuple[dict, str]] = []
        seen_nodes: set[str] = set()
        for raw_node in raw_nodes:
            sanitized = _sanitize_external_node(raw_node, is_meta=is_meta)
            if sanitized is None:
                continue
            node, canonical = sanitized
            if canonical in seen_nodes:
                continue
            seen_nodes.add(canonical)
            nodes.append((node, canonical))

        if nodes:
            prepared_sources.append({
                "id": source_id,
                "group_name": group_name,
                "nodes": nodes,
            })

    # Source IDs are persistent identities.  Sorting makes collision handling
    # and aggregate membership stable even if a DB query changes row order.
    prepared_sources.sort(key=lambda source: (source["id"], source["group_name"]))
    unique_sources: list[dict] = []
    seen_source_ids: set[int] = set()
    for source in prepared_sources:
        if source["id"] in seen_source_ids:
            continue
        seen_source_ids.add(source["id"])
        unique_sources.append(source)
    if not unique_sources:
        return result

    template_proxy_groups = list(proxy_groups)
    _isolate_external_nodes_from_template_groups(template_proxy_groups)
    used_names = _document_names(proxies, proxy_groups) | set(CLASH_RESERVED_PROXY_NAMES)
    source_group_counts = Counter(source["group_name"] for source in unique_sources)
    generated_groups: list[dict] = []

    # Reserve the fixed aggregate name even when a source happens to use it.
    source_blocked_names = used_names | {EXTERNAL_AGGREGATE_GROUP_NAME}
    for source in unique_sources:
        requested_group_name = source["group_name"]
        if (
            source_group_counts[requested_group_name] == 1
            and requested_group_name not in source_blocked_names
        ):
            actual_group_name = requested_group_name
        else:
            actual_group_name = _allocate_stable_name(
                requested_group_name,
                source_blocked_names,
                f"source:{source['id']}",
            )
        source_blocked_names.add(actual_group_name)
        used_names.add(actual_group_name)

        node_bases = [
            _clean_external_name(
                f"{EXTERNAL_NODE_NAME_PREFIX}{actual_group_name} / {node['name']}"
            )
            for node, _canonical in source["nodes"]
        ]
        node_base_counts = Counter(base for base in node_bases if base is not None)
        source_node_names: list[str] = []

        for (node, canonical), base_name in zip(source["nodes"], node_bases):
            if base_name is None:
                continue
            if node_base_counts[base_name] == 1 and base_name not in used_names:
                actual_node_name = base_name
            else:
                actual_node_name = _allocate_stable_name(
                    base_name,
                    used_names,
                    f"node:{source['id']}:{canonical}",
                )
            used_names.add(actual_node_name)
            source_blocked_names.add(actual_node_name)
            node["name"] = actual_node_name
            proxies.append(node)
            source_node_names.append(actual_node_name)

        if source_node_names:
            generated_groups.append({
                "name": actual_group_name,
                "type": "select",
                "proxies": source_node_names,
            })

    if not generated_groups:
        return result

    proxy_groups.extend(generated_groups)
    source_group_names = [group["name"] for group in generated_groups]

    aggregate_group = next(
        (
            group
            for group in template_proxy_groups
            if isinstance(group, dict)
            and group.get("name") == EXTERNAL_AGGREGATE_GROUP_NAME
            and group.get("type") == "select"
            and (group.get("proxies") is None or isinstance(group.get("proxies"), list))
        ),
        None,
    )
    if aggregate_group is not None:
        aggregate_name = EXTERNAL_AGGREGATE_GROUP_NAME
        aggregate_members = aggregate_group.setdefault("proxies", [])
        for group_name in source_group_names:
            if group_name not in aggregate_members:
                aggregate_members.append(group_name)
    else:
        if EXTERNAL_AGGREGATE_GROUP_NAME not in used_names:
            aggregate_name = EXTERNAL_AGGREGATE_GROUP_NAME
        else:
            aggregate_name = _allocate_stable_name(
                EXTERNAL_AGGREGATE_GROUP_NAME,
                used_names,
                "aggregate:external",
            )
        used_names.add(aggregate_name)
        proxy_groups.append({
            "name": aggregate_name,
            "type": "select",
            "proxies": source_group_names,
        })

    for group in template_proxy_groups:
        if (
            isinstance(group, dict)
            and group.get("name") == PRIMARY_PROXY_GROUP_NAME
            and group.get("type") == "select"
            and isinstance(group.get("proxies"), list)
            and aggregate_name not in group["proxies"]
        ):
            group["proxies"].append(aggregate_name)

    return result


def ordered_template_groups(groups: list, group_order: list[str] | None) -> list:
    """Stable ordering; new template groups follow saved groups, external stays last.

    Call before merging overlays, so generated source groups can only be appended.
    Group contents and member preferences are left intact.
    """
    positions = {name: index for index, name in enumerate(group_order or [])}
    def position(group):
        name = group.get("name") if isinstance(group, dict) else None
        if name == EXTERNAL_AGGREGATE_GROUP_NAME:
            return (1, 0)
        return (0, positions.get(name, len(positions)))
    return sorted(groups, key=position)


class ClashConfiguration(object):
    def __init__(self):
        self.data = {
            'proxies': [],
            'proxy-groups': [],
            # Some clients rely on "rules" option and will fail without it.
            'rules': []
        }
        self.proxy_remarks = []
        self.mux_template = render_template(MUX_TEMPLATE)
        user_agent_data = json.loads(render_template(USER_AGENT_TEMPLATE))

        if 'list' in user_agent_data and isinstance(user_agent_data['list'], list):
            self.user_agent_list = user_agent_data['list']
        else:
            self.user_agent_list = []

        try:
            self.settings = yaml.load(render_template(CLASH_SETTINGS_TEMPLATE), Loader=yaml.SafeLoader)
        except TemplateNotFound:
            self.settings = {}

        del user_agent_data

    def render(self, reverse=False, clash_overlay: dict | None = None, is_meta: bool = False, subscription_rules: list[str] | None = None, subscription_group_order: list[str] | None = None):
        if reverse:
            self.data['proxies'].reverse()

        yaml.add_representer(UUID, yml_uuid_representer)
        document = yaml.load(
            render_template(
                CLASH_SUBSCRIPTION_TEMPLATE,
                {"conf": self.data, "proxy_remarks": self.proxy_remarks}
            ),
            Loader=yaml.SafeLoader
        )
        if isinstance(document.get("proxy-groups"), list):
            document["proxy-groups"] = ordered_template_groups(document["proxy-groups"], subscription_group_order)
        if clash_overlay:
            document = merge_clash_overlay(
                document,
                clash_overlay,
                is_meta=is_meta,
            )
        if subscription_rules is not None:
            document["rules"] = list(subscription_rules)
            document["mode"] = "rule"
        return yaml.dump(
            document,
            sort_keys=False,
            allow_unicode=True,
        )

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return self.render()

    def _remark_validation(self, remark):
        if not remark in self.proxy_remarks:
            return remark
        c = 2
        while True:
            new = f'{remark} ({c})'
            if not new in self.proxy_remarks:
                return new
            c += 1

    def http_config(
            self,
            path="",
            host="",
            random_user_agent: bool = False,
    ):
        config = copy.deepcopy(self.settings.get("http-opts", {
            'headers': {}
        }))

        if path:
            config["path"] = [path]
        if host:
            config["Host"] = host
        if random_user_agent:
            if "headers" not in config:
                config["headers"] = {}
            config["header"]["User-Agent"] = choice(self.user_agent_list)

        return config

    def ws_config(
            self,
            path="",
            host="",
            max_early_data=None,
            early_data_header_name="",
            is_httpupgrade: bool = False,
            random_user_agent: bool = False,
    ):
        config = copy.deepcopy(self.settings.get("ws-opts", {}))
        if (host or random_user_agent) and "headers" not in config:
            config["headers"] = {}
        if path:
            config["path"] = path
        if host:
            config["headers"]["Host"] = host
        if random_user_agent:
            config["headers"]["User-Agent"] = choice(self.user_agent_list)
        if max_early_data and not is_httpupgrade:
            config["max-early-data"] = max_early_data
            config["early-data-header-name"] = early_data_header_name
        if is_httpupgrade:
            config["v2ray-http-upgrade"] = True
            config["v2ray-http-upgrade-fast-open"] = True

        return config

    def grpc_config(self, path=""):
        config = copy.deepcopy(self.settings.get("grpc-opts", {}))
        if path:
            config["grpc-service-name"] = path

        return config

    def h2_config(self, path="", host=""):
        config = copy.deepcopy(self.settings.get("h2-opts", {}))
        if path:
            config["path"] = path
        if host:
            config["host"] = [host]

        return config

    def tcp_config(self, path="", host=""):
        config = copy.deepcopy(self.settings.get("tcp-opts", {}))
        if path:
            config["path"] = [path]
        if host:
            if "headers" not in config:
                config["headers"] = {}
            config["headers"]["Host"] = host

        return config

    def make_node(self,
                  name: str,
                  remark: str,
                  type: str,
                  server: str,
                  port: int,
                  network: str,
                  tls: bool,
                  sni: str,
                  host: str,
                  path: str,
                  headers: str = '',
                  udp: bool = True,
                  alpn: str = '',
                  ais: bool = '',
                  mux_enable: bool = False,
                  random_user_agent: bool = False):

        if network in ["grpc", "gun"]:
            path = get_grpc_gun(path)

        if type == 'shadowsocks':
            type = 'ss'
        if network in ("http", "h2", "h3"):
            network = "h2"
        if network in ('tcp', 'raw') and headers == 'http':
            network = 'http'
        if network == 'httpupgrade':
            network = 'ws'
            is_httpupgrade = True
        else:
            is_httpupgrade = False
        node = {
            'name': remark,
            'type': type,
            'server': server,
            'port': port,
            'network': network,
            'udp': udp
        }

        if "?ed=" in path:
            path, max_early_data = path.split("?ed=")
            max_early_data, = max_early_data.split("/")
            max_early_data = int(max_early_data)
            early_data_header_name = "Sec-WebSocket-Protocol"
        else:
            max_early_data = None
            early_data_header_name = ""

        if type == 'ss':  # shadowsocks
            return node

        if tls:
            node['tls'] = True
            if type == 'trojan':
                node['sni'] = sni
            else:
                node['servername'] = sni
            if alpn:
                node['alpn'] = alpn.split(',')
            if ais:
                node['skip-cert-verify'] = ais

        if network == 'http':
            net_opts = self.http_config(
                path=path,
                host=host,
                random_user_agent=random_user_agent,
            )

        elif network == 'ws':
            net_opts = self.ws_config(
                path=path,
                host=host,
                max_early_data=max_early_data,
                early_data_header_name=early_data_header_name,
                is_httpupgrade=is_httpupgrade,
                random_user_agent=random_user_agent,
            )

        elif network == 'grpc' or network == 'gun':
            net_opts = self.grpc_config(path=path)

        elif network == 'h2':
            net_opts = self.h2_config(path=path, host=host)

        elif network in ('tcp', 'raw'):
            net_opts = self.tcp_config(path=path, host=host)

        else:
            net_opts = {}

        node[f'{network}-opts'] = net_opts

        mux_json = json.loads(self.mux_template)
        mux_config = mux_json["clash"]

        if mux_enable:
            node['smux'] = mux_config

        return node

    def add(self, remark: str, address: str, inbound: dict, settings: dict):
        # not supported by clash
        if inbound['network'] in ("kcp", "splithttp", "xhttp"):
            return

        proxy_remark = self._remark_validation(remark)

        node = self.make_node(
            name=remark,
            remark=proxy_remark,
            type=inbound['protocol'],
            server=address,
            port=inbound['port'],
            network=inbound['network'],
            tls=(inbound['tls'] == 'tls'),
            sni=inbound['sni'],
            host=inbound['host'],
            path=inbound['path'],
            headers=inbound['header_type'],
            udp=True,
            alpn=inbound.get('alpn', ''),
            ais=inbound.get('ais', False),
            mux_enable=inbound.get('mux_enable', False),
            random_user_agent=inbound.get("random_user_agent")
        )

        if inbound['protocol'] == 'vmess':
            node['uuid'] = settings['id']
            node['alterId'] = 0
            node['cipher'] = 'auto'

        elif inbound['protocol'] == 'trojan':
            node['password'] = settings['password']

        elif inbound['protocol'] == 'shadowsocks':
            node['password'] = settings['password']
            node['cipher'] = settings['method']

        else:
            return

        self.data['proxies'].append(node)
        self.proxy_remarks.append(proxy_remark)


class ClashMetaConfiguration(ClashConfiguration):
    def make_node(self,
                  name: str,
                  remark: str,
                  type: str,
                  server: str,
                  port: int,
                  network: str,
                  tls: bool,
                  sni: str,
                  host: str,
                  path: str,
                  headers: str = '',
                  udp: bool = True,
                  alpn: str = '',
                  fp: str = '',
                  pbk: str = '',
                  sid: str = '',
                  ais: bool = '',
                  mux_enable: bool = False,
                  random_user_agent: bool = False):
        node = super().make_node(
            name=name,
            remark=remark,
            type=type,
            server=server,
            port=port,
            network=network,
            tls=tls,
            sni=sni,
            host=host,
            path=path,
            headers=headers,
            udp=udp,
            alpn=alpn,
            ais=ais,
            mux_enable=mux_enable,
            random_user_agent=random_user_agent
        )
        if fp:
            node['client-fingerprint'] = fp
        if pbk:
            node['reality-opts'] = {"public-key": pbk, "short-id": sid}

        return node

    def add(self, remark: str, address: str, inbound: dict, settings: dict):
        # not supported by clash-meta
        if inbound['network'] in ("kcp", "splithttp", "xhttp") or (inbound['network'] == "quic" and inbound["header_type"] != "none"):
            return

        proxy_remark = self._remark_validation(remark)

        node = self.make_node(
            name=remark,
            remark=proxy_remark,
            type=inbound['protocol'],
            server=address,
            port=inbound['port'],
            network=inbound['network'],
            tls=(inbound['tls'] in ('tls', 'reality')),
            sni=inbound['sni'],
            host=inbound['host'],
            path=inbound['path'],
            headers=inbound['header_type'],
            udp=True,
            alpn=inbound.get('alpn', ''),
            fp=inbound.get('fp', ''),
            pbk=inbound.get('pbk', ''),
            sid=inbound.get('sid', ''),
            ais=inbound.get('ais', False),
            mux_enable=inbound.get('mux_enable', False),
            random_user_agent=inbound.get("random_user_agent")
        )

        if inbound['protocol'] == 'vmess':
            node['uuid'] = settings['id']
            node['alterId'] = 0
            node['cipher'] = 'auto'

        elif inbound['protocol'] == 'vless':
            node['uuid'] = settings['id']

            if inbound['network'] in ('tcp', 'raw', 'kcp') and inbound['header_type'] != 'http' and inbound['tls'] != 'none':
                node['flow'] = settings.get('flow', '')

        elif inbound['protocol'] == 'trojan':
            node['password'] = settings['password']

        elif inbound['protocol'] == 'shadowsocks':
            node['password'] = settings['password']
            node['cipher'] = settings['method']

        else:
            return

        self.data['proxies'].append(node)
        self.proxy_remarks.append(proxy_remark)
