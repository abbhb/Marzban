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

    def test_only_claude_has_direct_external_members_for_both_clients(self):
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
                self.assertEqual(groups[CLAUDE_PROXY_GROUP_NAME]['proxies'][-len(external):], external)
                for group in before['proxy-groups']:
                    if group['name'] != CLAUDE_PROXY_GROUP_NAME:
                        self.assertFalse(set(external) & set(groups[group['name']].get('proxies', [])))
                self.assertEqual(document, before)
                self.assertEqual(result['rules'], before['rules'])
                converted = prepare_shadowrocket(result)
                claude = next(group for group in converted['proxy-groups'] if group['name'] == CLAUDE_PROXY_GROUP_NAME)
                self.assertTrue(set(external) <= set(claude['proxies']))

    def test_no_overlay_keeps_fallback_choices(self):
        document = self.document()
        self.assertEqual(merge_clash_overlay(document, None, is_meta=True), document)
        group = next(group for group in document['proxy-groups'] if group['name'] == CLAUDE_PROXY_GROUP_NAME)
        self.assertEqual(group['proxies'][0], '🚀 节点选择')
