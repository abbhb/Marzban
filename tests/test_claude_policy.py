"""Claude policy separation and authorized external node selection."""
import copy
import unittest
from unittest.mock import patch

import yaml

from app.subscription.clash import (
    CLAUDE_PROXY_GROUP_NAME, EXTERNAL_NODE_NAME_PREFIX,
    ClashConfiguration, merge_clash_overlay,
)
from app.subscription.shadowrocket import prepare_shadowrocket
from tests.test_external_clash_renderer import _node


class ClaudePolicyTests(unittest.TestCase):
    def document(self):
        with patch('app.subscription.clash.CLASH_SUBSCRIPTION_TEMPLATE', 'clash/easyus.yml'):
            return yaml.safe_load(ClashConfiguration().render())

    def test_claude_and_anthropic_rules_are_separate(self):
        document = self.document()
        selected = [rule for rule in document['rules']
                    if any(value in rule for value in (',claude', ',anthropic'))]
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(rule.endswith(',' + CLAUDE_PROXY_GROUP_NAME) for rule in selected))
        self.assertIn('DOMAIN-SUFFIX,openai.com,🤖 AI 服务', document['rules'])
        names = [group['name'] for group in document['proxy-groups']]
        self.assertEqual(names[names.index('🤖 AI 服务') + 1], CLAUDE_PROXY_GROUP_NAME)

    def test_claude_uses_the_same_external_isolation_as_other_groups(self):
        for is_meta in (False, True):
            with self.subTest(is_meta=is_meta):
                document = self.document()
                before = copy.deepcopy(document)
                overlay = {'sources': [{'id': 1, 'group_name': 'Authorized', 'nodes': [
                    _node('US', proxy_type='vmess'),
                    _node('Meta only', proxy_type='vless'),
                    _node('Invalid', port=0),
                ]}]}
                result = merge_clash_overlay(document, overlay, is_meta=is_meta)
                external = [node['name'] for node in result['proxies']]
                self.assertEqual(len(external), 2 if is_meta else 1)
                self.assertTrue(all(name.startswith(EXTERNAL_NODE_NAME_PREFIX) for name in external))
                groups = {group['name']: group for group in result['proxy-groups']}
                self.assertFalse(set(external) & set(groups[CLAUDE_PROXY_GROUP_NAME]['proxies']))
                for group in before['proxy-groups']:
                    if group['name'] != CLAUDE_PROXY_GROUP_NAME:
                        self.assertFalse(set(external) & set(groups[group['name']].get('proxies', [])))
                self.assertEqual(document, before)
                self.assertEqual(result['rules'], before['rules'])
                converted = prepare_shadowrocket(result)
                claude = next(group for group in converted['proxy-groups'] if group['name'] == CLAUDE_PROXY_GROUP_NAME)
                self.assertFalse(set(external) & set(claude['proxies']))

    def test_no_overlay_keeps_fallback_choices(self):
        document = self.document()
        self.assertEqual(merge_clash_overlay(document, None, is_meta=True), document)
        group = next(group for group in document['proxy-groups'] if group['name'] == CLAUDE_PROXY_GROUP_NAME)
        self.assertEqual(group['proxies'][0], '🚀 节点选择')


    def test_flat_selector_contains_only_authorized_materialized_nodes(self):
        overlay = {'sources': [{'id': 1, 'group_name': 'Authorized', 'nodes': [
            _node('External', proxy_type='vmess'), _node('Invalid', port=0),
        ]}]}
        builder = ClashConfiguration()
        builder.data['proxies'] = [_node('US01', proxy_type='vmess'), _node('US02')]
        builder.inbound_proxy_names = {'US02': ['US02']}
        for fmt in ('meta', 'shadowrocket'):
            with self.subTest(fmt=fmt), patch('app.subscription.clash.CLASH_SUBSCRIPTION_TEMPLATE', 'clash/easyus.yml'):
                result = yaml.safe_load(builder.render(clash_overlay=overlay, is_meta=True))
                if fmt == 'shadowrocket':
                    result = prepare_shadowrocket(result)
                groups = {g['name']: g for g in result['proxy-groups']}
                self.assertEqual(groups['🚀 节点选择']['proxies'], [p['name'] for p in result['proxies']])
                self.assertNotIn('DIRECT', groups['🚀 节点选择']['proxies'])
                self.assertFalse({'🇺🇸 美国出口', '🇺🇸 美国直连', '🇭🇰 香港直连'} & set(groups))
                self.assertNotIn('x-mgma-flat-primary', result)
                known = set(groups) | {p['name'] for p in result['proxies']} | {'DIRECT', 'REJECT'}
                for group in groups.values():
                    self.assertTrue(set(group['proxies']) <= known)
        with patch('app.subscription.clash.CLASH_SUBSCRIPTION_TEMPLATE', 'clash/easyus.yml'):
            selected = yaml.safe_load(builder.render(clash_overlay=overlay, is_meta=True,
                plan_group_members={'🚀 节点选择': ['inbound:US02']}))
            self.assertEqual(next(g for g in selected['proxy-groups'] if g['name'] == '🚀 节点选择')['proxies'], ['US02'])
            empty = yaml.safe_load(ClashConfiguration().render())
            self.assertEqual(next(g for g in empty['proxy-groups'] if g['name'] == '🚀 节点选择')['proxies'], ['REJECT'])
