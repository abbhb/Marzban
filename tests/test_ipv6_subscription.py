import copy
import unittest
from unittest.mock import patch

import yaml

from app.subscription.clash import ClashConfiguration, ClashMetaConfiguration
from app.subscription.shadowrocket import prepare_shadowrocket


class Ipv6SubscriptionTests(unittest.TestCase):
    def render(self, nodes, *, meta=True, ipv6=False):
        document = {"ipv6": ipv6, "dns": {"enable": True, "ipv6": False},
                    "proxies": copy.deepcopy(nodes), "proxy-groups": [], "rules": ["MATCH,DIRECT"]}
        with patch('app.subscription.clash.render_template', side_effect=lambda name, context=None:
                   yaml.safe_dump(document) if name == 'clash/default.yml' else '{}'):
            configuration = ClashMetaConfiguration() if meta else ClashConfiguration()
            result = yaml.safe_load(configuration.render(is_meta=meta))
        return document, result

    def test_ipv6_server_enables_transport_without_changing_dns_aaaa_policy(self):
        for meta in (False, True):
            for address in ('2001:db8::10', '[2001:db8::10]'):
                before, result = self.render([{'name': 'v6', 'type': 'vless', 'server': address}], meta=meta)
                self.assertIs(result['ipv6'], True)
                self.assertEqual(result['dns'], before['dns'])
                self.assertEqual(result['proxies'], before['proxies'])
                self.assertEqual(result['rules'], before['rules'])
                self.assertIs(prepare_shadowrocket(result)['ipv6'], True)

    def test_only_the_separate_xhttp_downlink_requires_ipv6(self):
        nodes = [{'name': 'CDN up / IPv6 down', 'type': 'vless', 'server': 'cdn.example.test',
                  'xhttp-opts': {'download-settings': {'server': '2001:db8::10'}}}]
        before, result = self.render(nodes)
        self.assertIs(result['ipv6'], True)
        self.assertEqual(result['proxies'], before['proxies'])

    def test_ipv4_and_hostname_endpoints_preserve_template_preference(self):
        for setting in (False, True):
            for nodes in ([], [{'name': 'v4', 'server': '192.0.2.1'}],
                          [{'name': 'v4', 'server': '192.0.2.1', 'xhttp-opts': None}],
                          [{'name': 'host', 'server': 'proxy.example.test'}]):
                _, result = self.render(nodes, ipv6=setting)
                self.assertIs(result['ipv6'], setting)

    def test_ipv6_endpoints_from_authorized_external_overlay_are_also_enabled(self):
        document = {'ipv6': False, 'proxies': [], 'proxy-groups': [], 'rules': []}
        merged = {**document, 'proxies': [{'name': 'external IPv6', 'server': '2001:db8::20'}]}
        with patch('app.subscription.clash.render_template', return_value='{}'), \
             patch('app.subscription.clash.merge_clash_overlay', return_value=merged):
            result = yaml.safe_load(ClashMetaConfiguration().render(is_meta=True, clash_overlay={'sources': []}))
        self.assertIs(result['ipv6'], True)
