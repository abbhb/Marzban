import copy
import re
import unittest

from app.subscription.clash import (
    EXTERNAL_NODE_EXCLUDE_PATTERN, IPV6_NODE_PREFIX, present_ipv6_nodes,
)
from app.subscription.shadowrocket import prepare_shadowrocket


class Ipv6NodePresentationTests(unittest.TestCase):
    def document(self):
        return {'proxies': [
            {'name': 'v4 first', 'type': 'vless', 'server': '192.0.2.1', 'uuid': 'synthetic-one'},
            {'name': 'v6 first', 'type': 'vless', 'server': '2001:db8::1', 'uuid': 'synthetic-two'},
            {'name': 'v4 second', 'type': 'vless', 'server': '192.0.2.2', 'uuid': 'synthetic-three'},
            {'name': 'CDN up v6 down', 'type': 'vless', 'server': 'cdn.example.test',
             'xhttp-opts': {'download-settings': {'server': '2001:db8::2'}}},
        ], 'proxy-groups': [
            {'name': '🚀 节点选择', 'type': 'select', 'proxies': ['v4 first', 'v6 first', 'v4 second', 'CDN up v6 down', 'External']},
            {'name': 'AI', 'type': 'select', 'proxies': ['v4 second', 'v6 first', 'DIRECT']},
            {'name': 'External', 'type': 'select', 'proxies': ['DIRECT']},
        ], 'rules': ['DOMAIN,mp.example.test,DIRECT', 'MATCH,🚀 节点选择']}

    def test_prefix_and_stable_family_order_preserve_parameters_and_input(self):
        document = self.document(); before = copy.deepcopy(document)
        result = present_ipv6_nodes(document)
        expected = ['[ipv6] v6 first', '[ipv6] CDN up v6 down', 'v4 first', 'v4 second']
        self.assertEqual([n['name'] for n in result['proxies']], expected)
        self.assertEqual(result['proxy-groups'][0]['proxies'], expected + ['External'])
        self.assertEqual(result['proxy-groups'][1]['proxies'], ['v4 second', '[ipv6] v6 first', 'DIRECT'])
        self.assertEqual(result['rules'], before['rules'])
        self.assertEqual(document, before)
        strip = lambda node: {k:v for k,v in node.items() if k!='name'}
        for old in before['proxies']:
            new = next(n for n in result['proxies'] if n['name'] == (IPV6_NODE_PREFIX + old['name'] if 'v6' in old['name'] else old['name']))
            self.assertEqual(strip(new), strip(old))
        self.assertEqual(len(result['proxies']), len(before['proxies']))
        self.assertEqual(len(result['proxy-groups']), len(before['proxy-groups']))
        self.assertEqual(prepare_shadowrocket(result)['proxies'], result['proxies'])

    def test_repeated_presentation_is_idempotent(self):
        first = present_ipv6_nodes(self.document())
        self.assertEqual(present_ipv6_nodes(first), first)
        self.assertTrue(all(not n['name'].startswith('[ipv6] [ipv6]') for n in first['proxies']))

    def test_collisions_with_existing_node_and_group_names_are_resolved(self):
        document = self.document()
        document['proxies'][0]['name'] = '[ipv6] v6 first'
        document['proxy-groups'][0]['proxies'][0] = '[ipv6] v6 first'
        document['proxy-groups'].append({'name':'[ipv6] CDN up v6 down','type':'select','proxies':['DIRECT']})
        result = present_ipv6_nodes(document)
        names = [n['name'] for n in result['proxies']] + [g['name'] for g in result['proxy-groups']]
        self.assertEqual(len(names), len(set(names)))
        target = next(n['name'] for n in result['proxies'] if n['server']=='2001:db8::1')
        self.assertTrue(target.startswith('[ipv6] v6 first ['))
        self.assertIn(target, result['proxy-groups'][0]['proxies'])

    def test_rules_subrules_and_detours_follow_renamed_nodes(self):
        document = self.document()
        document['proxies'][0]['dialer-proxy'] = 'v6 first'
        document['proxy-groups'][0]['default-selected'] = 'v6 first'
        document['rules'] = ['IP-CIDR,192.0.2.0/24,v6 first,no-resolve','MATCH,v6 first']
        document['sub-rules'] = {'extra':['DOMAIN,example.test,CDN up v6 down']}
        result = present_ipv6_nodes(document)
        self.assertEqual(result['rules'], ['IP-CIDR,192.0.2.0/24,[ipv6] v6 first,no-resolve','MATCH,[ipv6] v6 first'])
        self.assertEqual(result['sub-rules']['extra'], ['DOMAIN,example.test,[ipv6] CDN up v6 down'])
        self.assertEqual(result['proxy-groups'][0]['default-selected'], '[ipv6] v6 first')
        self.assertEqual(next(n for n in result['proxies'] if n['name']=='v4 first')['dialer-proxy'], '[ipv6] v6 first')

    def test_external_namespace_filter_still_excludes_ipv6_external_nodes(self):
        document = {'proxies':[{'name':'MGMA-EXT · Airport / v6','server':'2001:db8::3'}], 'proxy-groups':[]}
        result = present_ipv6_nodes(document)
        name = result['proxies'][0]['name']
        self.assertTrue(name.startswith('[ipv6] MGMA-EXT · '))
        self.assertIsNotNone(re.search(EXTERNAL_NODE_EXCLUDE_PATTERN, name))
        self.assertIsNotNone(re.search(EXTERNAL_NODE_EXCLUDE_PATTERN, 'MGMA-EXT · Airport / v4'))

    def test_ipv4_only_document_has_no_new_nodes_or_placeholder(self):
        document = {'proxies':[{'name':'v4','server':'192.0.2.1'}], 'proxy-groups':[], 'rules':[]}
        self.assertEqual(present_ipv6_nodes(document), document)
