"""Focused tests for the external Clash/Mihomo render overlay."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import yaml

from app.subscription.clash import (
    EXTERNAL_AGGREGATE_GROUP_NAME,
    EXTERNAL_NODE_EXCLUDE_PATTERN,
    EXTERNAL_NODE_NAME_PREFIX,
    PRIMARY_PROXY_GROUP_NAME,
    ClashMetaConfiguration,
    merge_clash_overlay,
)


def _node(
    name: str,
    *,
    proxy_type: str = "vless",
    server: str = "edge.example",
    port: int | str = 443,
    **extra,
) -> dict:
    return {
        "name": name,
        "type": proxy_type,
        "server": server,
        "port": port,
        **extra,
    }


def _base_document() -> dict:
    return {
        "mode": "Global",
        "proxies": [_node("Local", proxy_type="vmess", server="local.example")],
        "proxy-groups": [
            {
                "name": "♻️ Automatic",
                "type": "url-test",
                "proxies": ["Local"],
            },
            {
                "name": PRIMARY_PROXY_GROUP_NAME,
                "type": "select",
                "proxies": ["♻️ Automatic"],
            },
        ],
        "rules": ["MATCH,🚀 节点选择"],
    }


class ExternalClashOverlayTests(unittest.TestCase):
    def test_meta_adds_namespaced_sources_aggregate_and_primary_reference(self) -> None:
        document = _base_document()
        overlay = {
            "sources": [
                {
                    "id": 20,
                    "group_name": "Airport B",
                    "nodes": [_node("Hong Kong", server="b.example")],
                    "rules": ["MATCH,DIRECT"],
                },
                {
                    "id": 10,
                    "group_name": "Airport A",
                    "nodes": [_node("Tokyo", server="a.example")],
                },
            ],
            "rules": ["MATCH,REJECT"],
            "dns": {"enable": True},
            "proxy-groups": [{"name": "Injected", "type": "select"}],
        }
        document_before = copy.deepcopy(document)
        overlay_before = copy.deepcopy(overlay)

        result = merge_clash_overlay(document, overlay, is_meta=True)

        self.assertEqual(document_before, document)
        self.assertEqual(overlay_before, overlay)
        self.assertEqual(["MATCH,🚀 节点选择"], result["rules"])
        self.assertNotIn("dns", result)

        proxies = {node["name"]: node for node in result["proxies"]}
        self.assertIn("Local", proxies)
        self.assertEqual(
            "a.example",
            proxies[f"{EXTERNAL_NODE_NAME_PREFIX}Airport A / Tokyo"]["server"],
        )
        self.assertEqual(
            "b.example",
            proxies[f"{EXTERNAL_NODE_NAME_PREFIX}Airport B / Hong Kong"]["server"],
        )

        groups = {group["name"]: group for group in result["proxy-groups"]}
        self.assertEqual(["Local"], groups["♻️ Automatic"]["proxies"])
        self.assertEqual(
            [f"{EXTERNAL_NODE_NAME_PREFIX}Airport A / Tokyo"],
            groups["Airport A"]["proxies"],
        )
        self.assertEqual(
            [f"{EXTERNAL_NODE_NAME_PREFIX}Airport B / Hong Kong"],
            groups["Airport B"]["proxies"],
        )
        self.assertEqual(
            ["Airport A", "Airport B"],
            groups[EXTERNAL_AGGREGATE_GROUP_NAME]["proxies"],
        )
        self.assertEqual(
            ["♻️ Automatic", EXTERNAL_AGGREGATE_GROUP_NAME],
            groups[PRIMARY_PROXY_GROUP_NAME]["proxies"],
        )
        self.assertNotIn("Injected", groups)

    def test_legacy_filters_mihomo_only_types_and_omits_empty_sources(self) -> None:
        overlay = {
            "sources": [
                {
                    "id": 1,
                    "group_name": "Meta only",
                    "nodes": [
                        _node("VLESS", proxy_type="vless"),
                        _node("Hysteria", proxy_type="hysteria"),
                        _node("Hysteria 2", proxy_type="hysteria2"),
                        _node("TUIC", proxy_type="tuic"),
                        _node("WireGuard", proxy_type="wireguard"),
                    ],
                },
                {
                    "id": 2,
                    "group_name": "Mixed",
                    "nodes": [
                        _node("VMess", proxy_type="vmess"),
                        _node("VLESS", proxy_type="vless", server="vless.example"),
                    ],
                },
            ]
        }

        legacy = merge_clash_overlay(_base_document(), overlay, is_meta=False)
        legacy_groups = {group["name"]: group for group in legacy["proxy-groups"]}
        self.assertNotIn("Meta only", legacy_groups)
        self.assertEqual(
            [f"{EXTERNAL_NODE_NAME_PREFIX}Mixed / VMess"],
            legacy_groups["Mixed"]["proxies"],
        )
        self.assertEqual(
            ["Mixed"],
            legacy_groups[EXTERNAL_AGGREGATE_GROUP_NAME]["proxies"],
        )

        meta = merge_clash_overlay(_base_document(), overlay, is_meta=True)
        meta_groups = {group["name"]: group for group in meta["proxy-groups"]}
        self.assertEqual(5, len(meta_groups["Meta only"]["proxies"]))
        self.assertEqual(2, len(meta_groups["Mixed"]["proxies"]))

    def test_invalid_nodes_are_skipped_and_names_are_sanitized(self) -> None:
        overlay = {
            "sources": [
                {
                    "id": 1,
                    "group_name": "  Safe\n Source  ",
                    "nodes": [
                        _node("  Good\n Node  ", port="443"),
                        _node("No server", server=""),
                        _node("Bad port", port=70000),
                        _node("Unsafe value", plugin={"bad"}),
                        _node("Dangling dialer", **{"dialer-proxy": "Upstream Group"}),
                        {"name": "No type", "server": "x", "port": 443},
                    ],
                },
                {
                    "id": 2,
                    "group_name": "Empty",
                    "nodes": [_node("Unsupported", proxy_type="not a type")],
                },
            ]
        }

        result = merge_clash_overlay(_base_document(), overlay, is_meta=True)
        groups = {group["name"]: group for group in result["proxy-groups"]}
        safe_node_name = f"{EXTERNAL_NODE_NAME_PREFIX}Safe Source / Good Node"
        self.assertEqual([safe_node_name], groups["Safe Source"]["proxies"])
        self.assertNotIn("Empty", groups)
        proxy = next(
            node for node in result["proxies"] if node["name"] == safe_node_name
        )
        self.assertEqual(443, proxy["port"])

    def test_duplicate_node_names_are_stable_and_never_overwrite_local_nodes(self) -> None:
        document = _base_document()
        colliding_name = f"{EXTERNAL_NODE_NAME_PREFIX}Airport / Same"
        document["proxies"].append(_node(colliding_name, proxy_type="vmess"))
        first = _node("Same", server="one.example")
        second = _node("Same", server="two.example")

        def rendered_names(nodes: list[dict]) -> dict[str, str]:
            result = merge_clash_overlay(
                document,
                {"sources": [{"id": 7, "group_name": "Airport", "nodes": nodes}]},
                is_meta=True,
            )
            return {
                node["server"]: node["name"]
                for node in result["proxies"]
                if node.get("server") in {"one.example", "two.example"}
            }

        forward = rendered_names([first, second])
        reverse = rendered_names([second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(2, len(set(forward.values())))
        self.assertNotIn(colliding_name, forward.values())
        self.assertTrue(
            all(name.startswith(f"{colliding_name} [") for name in forward.values())
        )

    def test_duplicate_source_group_names_resolve_stably_by_source_id(self) -> None:
        sources = [
            {
                "id": 2,
                "group_name": "Same Airport",
                "nodes": [_node("Two", server="two.example")],
            },
            {
                "id": 1,
                "group_name": "Same Airport",
                "nodes": [_node("One", server="one.example")],
            },
        ]

        def source_groups(order: list[dict]) -> dict[str, str]:
            result = merge_clash_overlay(
                _base_document(),
                {"sources": order},
                is_meta=True,
            )
            proxies = {proxy["name"]: proxy for proxy in result["proxies"]}
            mapping = {}
            for group in result["proxy-groups"]:
                if group.get("type") != "select" or len(group.get("proxies", [])) != 1:
                    continue
                member = proxies.get(group["proxies"][0])
                if member and member.get("server") in {"one.example", "two.example"}:
                    mapping[member["server"]] = group["name"]
            return mapping

        forward = source_groups(sources)
        reverse = source_groups(list(reversed(sources)))
        self.assertEqual(forward, reverse)
        self.assertEqual(2, len(set(forward.values())))
        self.assertTrue(all(name.startswith("Same Airport [") for name in forward.values()))

    def test_source_group_cannot_shadow_a_builtin_proxy_name(self) -> None:
        result = merge_clash_overlay(
            _base_document(),
            {
                "sources": [
                    {"id": 9, "group_name": "DIRECT", "nodes": [_node("HK")]}
                ]
            },
            is_meta=True,
        )
        generated = [
            group
            for group in result["proxy-groups"]
            if group.get("type") == "select" and group["name"].startswith("DIRECT [")
        ]
        self.assertEqual(1, len(generated))

    def test_existing_select_aggregate_is_reused_without_duplicate_references(self) -> None:
        document = _base_document()
        document["proxy-groups"].append({
            "name": EXTERNAL_AGGREGATE_GROUP_NAME,
            "type": "select",
            "proxies": ["DIRECT"],
        })
        document["proxy-groups"][1]["proxies"].append(EXTERNAL_AGGREGATE_GROUP_NAME)
        overlay = {
            "sources": [{"id": 1, "group_name": "Airport", "nodes": [_node("HK")]}]
        }

        result = merge_clash_overlay(document, overlay, is_meta=True)
        aggregates = [
            group
            for group in result["proxy-groups"]
            if group.get("name") == EXTERNAL_AGGREGATE_GROUP_NAME
        ]
        self.assertEqual(1, len(aggregates))
        self.assertEqual(["DIRECT", "Airport"], aggregates[0]["proxies"])
        primary = next(
            group for group in result["proxy-groups"] if group["name"] == PRIMARY_PROXY_GROUP_NAME
        )
        self.assertEqual(1, primary["proxies"].count(EXTERNAL_AGGREGATE_GROUP_NAME))

    def test_existing_include_all_groups_exclude_external_namespace(self) -> None:
        document = _base_document()
        document["proxy-groups"].extend([
            {
                "name": "All proxies",
                "type": "select",
                "include-all-proxies": True,
            },
            {
                "name": "Hong Kong",
                "type": "url-test",
                "include-all-proxies": True,
                "filter": "(?i)HK|Hong Kong",
                "exclude-filter": "(?i)Expire|Traffic",
            },
        ])
        overlay = {
            "sources": [{"id": 1, "group_name": "Airport", "nodes": [_node("HK")]}]
        }

        result = merge_clash_overlay(document, overlay, is_meta=True)
        groups = {group["name"]: group for group in result["proxy-groups"]}
        self.assertEqual(
            EXTERNAL_NODE_EXCLUDE_PATTERN,
            groups["All proxies"]["exclude-filter"],
        )
        self.assertEqual(
            f"(?i)Expire|Traffic|{EXTERNAL_NODE_EXCLUDE_PATTERN}",
            groups["Hong Kong"]["exclude-filter"],
        )

        # Running the pure merge again must not grow the expression.
        repeated = merge_clash_overlay(result, overlay, is_meta=True)
        repeated_groups = {group["name"]: group for group in repeated["proxy-groups"]}
        self.assertEqual(
            1,
            repeated_groups["Hong Kong"]["exclude-filter"].count(
                EXTERNAL_NODE_EXCLUDE_PATTERN
            ),
        )

    def test_non_select_aggregate_collision_uses_one_deterministic_fallback(self) -> None:
        document = _base_document()
        document["proxy-groups"].append({
            "name": EXTERNAL_AGGREGATE_GROUP_NAME,
            "type": "url-test",
            "proxies": ["Local"],
        })
        overlay = {
            "sources": [{"id": 1, "group_name": "Airport", "nodes": [_node("HK")]}]
        }

        first = merge_clash_overlay(document, overlay, is_meta=True)
        second = merge_clash_overlay(document, overlay, is_meta=True)
        self.assertEqual(first, second)
        names = [group["name"] for group in first["proxy-groups"]]
        self.assertEqual(len(names), len(set(names)))
        aggregate_fallback = next(
            group["name"]
            for group in first["proxy-groups"]
            if group.get("type") == "select"
            and group["name"].startswith(f"{EXTERNAL_AGGREGATE_GROUP_NAME} [")
        )
        primary = next(
            group for group in first["proxy-groups"] if group["name"] == PRIMARY_PROXY_GROUP_NAME
        )
        self.assertIn(aggregate_fallback, primary["proxies"])

    def test_bad_document_shape_and_empty_overlay_are_non_destructive(self) -> None:
        bad_document = {"proxies": {"not": "a list"}, "proxy-groups": []}
        overlay = {
            "sources": [{"id": 1, "group_name": "Airport", "nodes": [_node("HK")]}]
        }
        result = merge_clash_overlay(bad_document, overlay, is_meta=True)
        self.assertEqual(bad_document, result)
        self.assertIsNot(bad_document, result)

        document = _base_document()
        empty = merge_clash_overlay(document, {"sources": []}, is_meta=True)
        self.assertEqual(document, empty)
        self.assertIsNot(document, empty)

    def test_render_applies_overlay_after_template_materialization(self) -> None:
        def fake_render(template: str, context=None) -> str:
            if template.endswith("mux/default.json"):
                return '{"clash": {}}'
            if template.endswith("user_agent/default.json"):
                return '{"list": []}'
            if template.endswith("clash/settings.yml"):
                return "{}"
            return yaml.dump(_base_document(), sort_keys=False, allow_unicode=True)

        overlay = {
            "sources": [{"id": 1, "group_name": "Airport", "nodes": [_node("HK")]}]
        }
        with patch("app.subscription.clash.render_template", side_effect=fake_render):
            rendered = yaml.safe_load(
                ClashMetaConfiguration().render(
                    clash_overlay=overlay,
                    is_meta=True,
                )
            )

        groups = {group["name"]: group for group in rendered["proxy-groups"]}
        self.assertEqual(
            [f"{EXTERNAL_NODE_NAME_PREFIX}Airport / HK"],
            groups["Airport"]["proxies"],
        )
        self.assertEqual(["Airport"], groups[EXTERNAL_AGGREGATE_GROUP_NAME]["proxies"])


if __name__ == "__main__":
    unittest.main()
