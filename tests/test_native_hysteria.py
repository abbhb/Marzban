"""Regression coverage for node-scoped, panel-managed Hysteria 2."""
import unittest
from unittest.mock import MagicMock, patch
import yaml

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.db.models import Proxy, User
from app.models.proxy import HysteriaSettings, ProxyInbound, ProxyTypes
from app.services import commerce
from app.subscription.clash import ClashMetaConfiguration
from app.subscription.v2ray import V2rayShareLink
from app.xray.config import XRayConfig
from app.xray.core import XRayCore
from app.xray.node import ReSTXRayNode
from app.xray import operations
from xray_api.types.account import HysteriaAccount


def document(node_ids=(3,)):
    return {'x-marzban-dedicated-node-ids': [3], 'inbounds': [
        {'tag': 'legacy', 'port': 12345, 'protocol': 'vless',
         'settings': {'clients': [], 'decryption': 'none'}},
        {'tag': 'HY2', 'port': 443, 'protocol': 'hysteria',
         'x-marzban-node-ids': list(node_ids),
         'settings': {'version': 2, 'clients': []},
         'streamSettings': {'network': 'hysteria', 'security': 'tls',
                            'hysteriaSettings': {'version': 2},
                            'tlsSettings': {'certificates': []}}},
    ], 'outbounds': [{'tag': 'direct', 'protocol': 'freedom'}]}


class HysteriaConfigTests(unittest.TestCase):
    def test_inbound_response_keeps_scoped_nodes_and_shared_scope(self):
        config = XRayConfig(document(), api_port=9000)
        scoped = ProxyInbound.model_validate(config.inbounds_by_tag['HY2']).model_dump()
        shared = ProxyInbound.model_validate(config.inbounds_by_tag['legacy']).model_dump()
        self.assertEqual([3], scoped['node_ids'])
        self.assertIsNone(shared['node_ids'])

    def test_session_adoption_preserves_running_remote_core(self):
        node = ReSTXRayNode.__new__(ReSTXRayNode)
        node.address, node.port = 'example.test', 1
        node.session = MagicMock()
        node.check_connection = MagicMock(return_value=True)
        node.check_started = MagicMock(return_value=True)
        node._api = MagicMock()
        with patch('app.xray.node.ssl.get_server_certificate', return_value='cert'), \
             patch('app.xray.node.string_to_temp_file') as temp, \
             patch('app.xray.node.grpc.channel_ready_future') as ready:
            temp.return_value.name = '/temporary/cert'
            node.adopt_session('session')
        self.assertTrue(node._started)
        node.check_connection.assert_called_once()
        node.check_started.assert_called_once()
        ready.return_value.result.assert_called_once()
        self.assertEqual('session', node._session_id)

    def test_handoff_failure_retains_protection_and_never_calls_start(self):
        node = MagicMock()
        node.adopt_session.side_effect = ConnectionError('unavailable')
        with patch.object(operations, '_handoff_sessions', {9: 'session'}), \
             patch.object(operations, '_handoff_path', None):
            with self.assertRaises(ConnectionError):
                operations._adopt_handoff(9, node)
            self.assertIn(9, operations._handoff_sessions)
        node.start.assert_not_called()
        node.connect.assert_not_called()

    def test_x25519_parser_accepts_old_and_new_xray_output(self):
        core = XRayCore.__new__(XRayCore)
        core.executable_path = 'xray'
        for output in (b'Private key: private\nPublic key: public\n',
                       b'PrivateKey: private\nPassword (PublicKey): public\nHash32: digest\n'):
            with self.subTest(output=output), patch('subprocess.check_output', return_value=output):
                self.assertEqual({'private_key': 'private', 'public_key': 'public'},
                                 core.get_x25519('private'))

    def test_scoping_preserves_unrelated_inbounds_and_shared_config(self):
        config = XRayConfig(document(), api_port=12346)
        self.assertEqual('hysteria', config.inbounds_by_tag['HY2']['protocol'])
        self.assertEqual([3], config.inbounds_by_tag['HY2']['node_ids'])
        for node_id in (None, 1, 2):
            by_tag = {x['tag']: x for x in config.for_node(node_id)['inbounds']}
            self.assertIn('legacy', by_tag)
            self.assertNotIn('HY2', by_tag)
        target = {x['tag']: x for x in config.for_node(3)['inbounds']}
        self.assertIn('HY2', target)
        self.assertNotIn('legacy', target)
        self.assertNotIn('x-marzban-node-ids', target['HY2'])
        self.assertEqual([3], config.get_inbound('HY2')['x-marzban-node-ids'])

    def test_invalid_or_empty_scope_fails_closed(self):
        for nodes in ([], [0], ['3'], [True], [3, 3]):
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                XRayConfig(document(nodes), api_port=12346)

    def test_hy2_requires_dedicated_target(self):
        doc = document()
        doc['x-marzban-dedicated-node-ids'] = []
        with self.assertRaises(ValueError):
            XRayConfig(doc, api_port=12346)

    def test_only_changed_node_is_restarted_when_adding_hy2(self):
        from app.routers import core
        old_doc = document()
        old_doc.pop('x-marzban-dedicated-node-ids')
        old_doc['inbounds'] = [old_doc['inbounds'][0]]
        old = XRayConfig(old_doc, api_port=12346)
        nodes = {1: MagicMock(connected=True), 3: MagicMock(connected=True)}
        with patch.object(core.xray, 'config', old), patch.object(core.xray, 'nodes', nodes), \
             patch.object(XRayConfig, 'include_db_users', lambda self: self), \
             patch.object(core, '_write_core_document'), \
             patch.object(core.xray.core, 'restart') as restart_main, \
             patch.object(core.xray.operations, 'restart_node') as restart_node, \
             patch.object(core.xray.hosts, 'update'):
            core.modify_core_config(document(), admin=None)
        restart_main.assert_not_called()
        self.assertEqual([3], [call.args[0] for call in restart_node.call_args_list])

    def test_account_and_protocol_match_xray_protobuf(self):
        message = HysteriaAccount(email='test', auth='secret').message
        self.assertEqual('xray.proxy.hysteria.account.Account', message.type)
        self.assertEqual(b'\x0a\x06secret', message.value)
        self.assertNotEqual(HysteriaSettings().auth, HysteriaSettings().auth)

    def test_clash_node_is_native_and_uses_account_auth(self):
        config = ClashMetaConfiguration.__new__(ClashMetaConfiguration)
        config.data = {'proxies': []}
        config.proxy_remarks = []
        inbound = {'protocol': 'hysteria', 'network': 'hysteria', 'tls': 'tls',
                   'port': 443, 'sni': 'media.example.test', 'ais': False}
        config.add('🇺🇸美国 03 · HY2 直连', '203.0.113.1', inbound, {'auth': 'secret'})
        self.assertEqual([{'name': '🇺🇸美国 03 · HY2 直连', 'type': 'hysteria2',
                           'server': '203.0.113.1', 'port': 443, 'password': 'secret',
                           'sni': 'media.example.test', 'udp': True,
                           'skip-cert-verify': False}], config.data['proxies'])
        link = V2rayShareLink()
        link.add('route', '203.0.113.1', {**inbound, 'path': '', 'header_type': ''}, {'auth': 'secret'})
        self.assertTrue(link.links[0].startswith('hysteria2://secret@203.0.113.1:443/'))

    def test_full_subscription_renders_native_node_in_primary_selector(self):
        from app.subscription import share
        inbound = {'tag': 'HY2', 'protocol': 'hysteria', 'network': 'hysteria',
                   'tls': 'tls', 'port': 443, 'sni': ['media.example.test'],
                   'host': [], 'path': '', 'header_type': ''}
        host = {'remark': '🇺🇸美国 03 · HY2 直连', 'address': ['203.0.113.1'],
                'sni': ['media.example.test'], 'host': [], 'path': None,
                'port': None, 'tls': None, 'alpn': None, 'fingerprint': None,
                'allowinsecure': False, 'mux_enable': False, 'fragment_setting': None,
                'noise_setting': None, 'random_user_agent': False}
        template = {'x-mgma-flat-primary': True, 'proxies': [],
                    'proxy-groups': [{'name': '🚀 节点选择', 'type': 'select', 'proxies': []}],
                    'rules': []}
        def render(name, context=None):
            if name == 'clash/default.yml':
                result = dict(template)
                result['proxies'] = context['conf']['proxies']
                return yaml.safe_dump(result, allow_unicode=True)
            return '{}'
        with patch.object(share.xray.config, 'inbounds_by_tag', {'HY2': inbound}), \
             patch.object(share.xray, 'hosts', {'HY2': [host]}), \
             patch('app.subscription.clash.render_template', side_effect=render), \
             patch('app.subscription.clash.CLASH_SUBSCRIPTION_TEMPLATE', 'clash/default.yml'):
            result = yaml.safe_load(share.generate_clash_subscription(
                {ProxyTypes.Hysteria: HysteriaSettings(auth='secret')},
                {ProxyTypes.Hysteria: ['HY2']}, {'used_traffic': 0}, False, is_meta=True))
        self.assertEqual('hysteria2', result['proxies'][0]['type'])
        self.assertEqual(['🇺🇸美国 03 · HY2 直连'], result['proxy-groups'][0]['proxies'])
        self.assertEqual(1, len(result['proxy-groups']))


class HysteriaPlanTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        inbounds = {'VLESS': {'tag': 'VLESS', 'protocol': 'vless'},
                    'HY2-A': {'tag': 'HY2-A', 'protocol': 'hysteria'},
                    'HY2-B': {'tag': 'HY2-B', 'protocol': 'hysteria'}}
        self.ctx = patch.multiple(commerce.xray.config, inbounds_by_tag=inbounds,
                                  inbounds_by_protocol={ProxyTypes.VLESS: [inbounds['VLESS']],
                                                        ProxyTypes.Hysteria: [inbounds['HY2-A'], inbounds['HY2-B']]})
        self.ctx.start()
        self.addCleanup(self.ctx.stop)
        self.user = User(username='native-hy2-test', proxies=[Proxy(type=ProxyTypes.VLESS.value,
                          settings={'id': 'a7f8da8c-b2cd-4435-8e91-1d5c5a496f55'})])
        self.db.add(self.user)
        self.db.flush()

    def test_grant_and_revoke_do_not_change_vless_or_grant_other_hy2(self):
        commerce.validate_plan_inbounds(['VLESS', 'HY2-A'])
        self.assertTrue(commerce._apply_plan_hysteria(self.db, self.user, ['VLESS', 'HY2-A']))
        self.db.flush()
        proxy = next(p for p in self.user.proxies if ProxyTypes(p.type) == ProxyTypes.Hysteria)
        auth = proxy.settings['auth']
        self.assertEqual({'HY2-B'}, {x.tag for x in proxy.excluded_inbounds})
        self.assertTrue(commerce._apply_plan_hysteria(self.db, self.user, ['VLESS']))
        self.assertEqual({'HY2-A', 'HY2-B'}, {x.tag for x in proxy.excluded_inbounds})
        self.assertEqual(auth, proxy.settings['auth'])
        self.assertTrue(any(ProxyTypes(p.type) == ProxyTypes.VLESS for p in self.user.proxies))


from tests.test_commerce import CommerceDatabaseTestCase
from app.models.commerce import SubscriptionPlanUpdate


class HysteriaCommerceLifecycleTests(CommerceDatabaseTestCase):
    def setUp(self):
        super().setUp()
        by_tag = commerce.xray.config.inbounds_by_tag
        by_type = commerce.xray.config.inbounds_by_protocol
        new = [{'tag': 'HY2-A', 'protocol': 'hysteria'}, {'tag': 'HY2-B', 'protocol': 'hysteria'}]
        by_tag.update({i['tag']: i for i in new})
        by_type[ProxyTypes.Hysteria] = new

    def test_purchase_and_plan_change_preserve_vless_and_hy2_credentials(self):
        plan = self.create_plan(price_minor=0, inbound_tags=['HK01', 'HY2-A'])
        account = self.register()
        result = commerce.purchase_plan(self.db, account, plan_id=plan.id, idempotency_key='hy2-purchase-0001')
        user = result.user
        self.assertEqual(['HK01'], user.inbounds[ProxyTypes.VLESS])
        self.assertEqual(['HY2-A'], user.inbounds[ProxyTypes.Hysteria])
        hy = next(p for p in user.proxies if ProxyTypes(p.type) == ProxyTypes.Hysteria)
        vl = next(p for p in user.proxies if ProxyTypes(p.type) == ProxyTypes.VLESS)
        auth, vless_id = hy.settings['auth'], vl.settings['id']
        plan.inbound_tags = ['HK01', 'HY2-B']
        self.db.flush()
        affected = commerce.reconcile_plan_entitlements(self.db, plan)
        self.db.refresh(user)
        self.assertEqual(['HY2-B'], user.inbounds[ProxyTypes.Hysteria])
        self.assertEqual(['HK01'], user.inbounds[ProxyTypes.VLESS])
        self.assertEqual(auth, hy.settings['auth'])
        self.assertEqual(vless_id, vl.settings['id'])
        self.assertEqual([user.id], [uid for uid, _ in affected])
        plan.inbound_tags = ['HK01']
        self.db.flush()
        commerce.reconcile_plan_entitlements(self.db, plan)
        self.db.refresh(user)
        self.assertEqual([], user.inbounds[ProxyTypes.Hysteria])
        self.assertEqual(['HK01'], user.inbounds[ProxyTypes.VLESS])
