"""Plan route selection is enforced before every client format is rendered."""
import copy
import base64
import importlib
import json
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import BackgroundTasks
from pydantic import ValidationError
import sqlalchemy as sa
import yaml

from app import app, xray
from app.db import get_db
from app.db.models import SubscriptionPlan
from app.models.commerce import SubscriptionPlanCreate, SubscriptionPlanUpdate, SubscriptionPlanResponse
from app.models.proxy import ProxyTypes
from app.models.user import UserResponse
from app.routers import commerce as commerce_router
from app.routers.subscription import build_subscription_response
from app.services import commerce, local_nodes
from tests.test_commerce import CommerceDatabaseTestCase
from tests.test_xhttp_subscription import inbound as xhttp_inbound


def fixtures():
    direct = {**xhttp_inbound(), 'tag': 'VISION', 'network': 'tcp', 'sni': ['origin.example.test'], 'host': []}
    base = {**xhttp_inbound(), 'tag': 'XHTTP', 'sni': ['origin.example.test'], 'host': []}
    profiles = []
    for label, address, down in [('IPv4', '192.0.2.2', None), ('IPv6', '2001:db8::2', None),
                                  ('CDN up / IPv6 down', 'cdn.example.test', '2001:db8::2')]:
        transport = {'path': base['path'], 'mode': 'packet-up'}
        if down:
            transport['downloadSettings'] = {
                'address': down, 'port': 443, 'security': 'tls',
                'tlsSettings': {'serverName': 'origin.example.test'},
                'xhttpSettings': {'path': base['path']},
            }
        profiles.append({'label': label, 'address': address, 'port': 443,
                         'streamSettings': {'network': 'xhttp', 'security': 'tls',
                                            'tlsSettings': {'serverName': 'origin.example.test'},
                                            'xhttpSettings': transport}})
    base['xhttpProfiles'] = profiles
    host = {'remark': 'Synthetic {USERNAME}', 'address': ['192.0.2.2'], 'port': None,
            'sni': [], 'host': [], 'path': None, 'tls': None, 'alpn': None,
            'fingerprint': None, 'allowinsecure': False, 'mux_enable': False,
            'fragment_setting': None, 'noise_setting': None, 'random_user_agent': False}
    v6host = {**host, 'remark': 'Synthetic IPv6 {USERNAME}', 'address': ['2001:db8::2']}
    return {'VISION': direct, 'XHTTP': base}, {'VISION': [host, v6host], 'XHTTP': [copy.deepcopy(host)]}


class LocalNodeEntitlementsTests(CommerceDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.inbounds, self.hosts = fixtures()
        config = patch.multiple(xray.config, inbounds_by_tag=self.inbounds,
                                inbounds_by_protocol={ProxyTypes.VLESS: list(self.inbounds.values())})
        config.start(); self.addCleanup(config.stop)
        hosts = patch.object(xray, 'hosts', self.hosts)
        hosts.start(); self.addCleanup(hosts.stop)
        self.selection = {item['tag']: [node['id'] for node in item['nodes'] if node['ipv6']]
                          for item in local_nodes.node_catalog()}
        from app.subscription import clash
        from config import CLASH_SUBSCRIPTION_TEMPLATE
        original_render = clash.render_template
        def template(name, context=None):
            if name == CLASH_SUBSCRIPTION_TEMPLATE:
                return json.dumps({'ipv6': False, 'proxies': context['conf']['proxies'],
                                       'proxy-groups': [{'name': '🚀 节点选择', 'type': 'select',
                                                         'proxies': context['proxy_remarks']}],
                                       'rules': ['MATCH,🚀 节点选择']}, ensure_ascii=False, default=str)
            return original_render(name, context)
        renderer = patch.object(clash, 'render_template', side_effect=template)
        renderer.start(); self.addCleanup(renderer.stop)
        groups = patch('app.services.plan_groups.group_catalog', return_value=['🚀 节点选择'])
        groups.start(); self.addCleanup(groups.stop)

    def make_plan(self, **extra):
        return commerce.create_plan(self.db, SubscriptionPlanCreate(
            name='IPv6 only', price_minor=0, duration_days=30, data_limit=1024**3,
            inbound_tags=['VISION', 'XHTTP'], **extra))

    def subscribe(self, plan):
        account = self.register()
        commerce.grant_plan(self.db, account, plan, actor_admin='test', idempotency_key='test-route-grant')
        self.db.expire_all()
        return account.proxy_user

    def test_catalog_is_safe_and_identifies_ipv6_uplink_and_downlink(self):
        catalog = local_nodes.node_catalog()
        self.assertEqual([len(item['nodes']) for item in catalog], [2, 3])
        self.assertEqual([sum(node['ipv6'] for node in item['nodes']) for item in catalog], [1, 2])
        for item in catalog:
            for node in item['nodes']:
                self.assertEqual(set(node), {'id', 'name', 'ipv6', 'enabled'})
                self.assertEqual(node['name'].startswith('[ipv6] '), node['ipv6'])
        before = copy.deepcopy(catalog)
        self.hosts['VISION'].reverse()
        self.inbounds['XHTTP']['xhttpProfiles'].reverse()
        self.inbounds['XHTTP']['xhttpProfiles'][0]['label'] = 'renamed'
        self.inbounds['XHTTP']['xhttpProfiles'][0]['enabled'] = False
        after = local_nodes.node_catalog()
        self.assertEqual({node['id'] for item in before for node in item['nodes']},
                         {node['id'] for item in after for node in item['nodes']})

    def test_plan_selection_persists_and_does_not_change_credentials(self):
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        schema = UserResponse.model_validate(user)
        self.assertEqual(schema.local_node_selections, self.selection)
        self.assertNotIn('local_node_selections', schema.model_dump())
        self.assertEqual(SubscriptionPlanResponse.model_validate(plan).local_node_selections, self.selection)
        credentials = copy.deepcopy(user.proxies[0].settings)
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(local_node_selections={}))
        self.db.expire_all()
        self.assertEqual(user.proxies[0].settings, credentials)
        self.assertEqual(UserResponse.model_validate(user).local_node_selections, {})

    def test_all_exports_respect_host_selection_and_never_fallback_to_xhttp_base(self):
        user = self.subscribe(self.make_plan(local_node_selections=self.selection))
        schema = UserResponse.model_validate(user)
        self.assertEqual(len(schema.links), 1)
        self.assertIn('2001:db8::2', schema.links[0])
        for client in ['clash-meta', 'shadowrocket']:
            result = yaml.safe_load(build_subscription_response(schema, client_type=client, db=self.db, user_id=user.id).body)
            self.assertEqual(len(result['proxies']), 3)
            self.assertTrue(all(node['name'].startswith('[ipv6] ') for node in result['proxies']))
            self.assertTrue(all(node.get('uuid') == user.proxies[0].settings['id'] for node in result['proxies']))
            for group in result['proxy-groups']:
                self.assertFalse(any(name.startswith('Synthetic') for name in group.get('proxies', [])))
            self.assertIs(result['ipv6'], True)
        for client in ['v2ray', 'v2ray-json', 'sing-box', 'outline', 'clash']:
            output = build_subscription_response(schema, client_type=client, db=self.db, user_id=user.id).body.decode()
            if client == 'v2ray':
                output = base64.b64decode(output).decode()
            self.assertNotIn('192.0.2.2', output, client)
            self.assertNotIn('cdn.example.test', output, client)

    def test_invalid_or_cross_inbound_selection_rejected_atomically(self):
        for selection in [{'XHTTP': self.selection['VISION']}, {'SECRET': self.selection['VISION']}, {'XHTTP': ['f' * 64]}]:
            with self.subTest(selection=selection), self.assertRaises(commerce.PlanConfigurationError):
                self.make_plan(local_node_selections=selection)
            self.db.rollback()
        for selection in [{'XHTTP': []}, {'XHTTP': ['f' * 64] * 2}, {'XHTTP': ['unknown']}, None]:
            with self.subTest(selection=selection), self.assertRaises(ValidationError):
                SubscriptionPlanUpdate(local_node_selections=selection)
        self.assertEqual(self.db.query(SubscriptionPlan).count(), 0)

    def test_plan_update_keeps_restrictions_and_removed_inbound_drops_only_its_selection(self):
        plan = self.make_plan(local_node_selections=self.selection)
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(description='changed'))
        self.assertEqual(plan.local_node_selections, self.selection)
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(inbound_tags=['VISION']))
        self.assertEqual(plan.local_node_selections, {'VISION': self.selection['VISION']})
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(local_node_selections=self.selection))
        self.assertEqual(plan.local_node_selections, {'VISION': self.selection['VISION']})

    def test_disabled_new_or_changed_routes_never_expand_a_custom_selection(self):
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        self.inbounds['XHTTP']['xhttpProfiles'][1]['enabled'] = False
        changed = self.inbounds['XHTTP']['xhttpProfiles'][2]
        changed['streamSettings']['xhttpSettings']['downloadSettings']['address'] = '2001:db8::99'
        new = copy.deepcopy(self.inbounds['XHTTP']['xhttpProfiles'][0])
        new['label'] = 'new IPv6'; new['address'] = '2001:db8::99'
        self.inbounds['XHTTP']['xhttpProfiles'].append(new)
        result = yaml.safe_load(build_subscription_response(UserResponse.model_validate(user), client_type='clash-meta', db=self.db, user_id=user.id).body)
        self.assertEqual(len(result['proxies']), 1)
        self.assertEqual(result['proxies'][0]['server'], '2001:db8::2')

    def test_default_all_routes_and_unmanaged_accounts_keep_existing_exports(self):
        original = copy.deepcopy((self.inbounds, self.hosts))
        plan = self.make_plan()
        user = self.subscribe(plan)
        schema = UserResponse.model_validate(user)
        result = yaml.safe_load(build_subscription_response(schema, client_type='clash-meta', db=self.db, user_id=user.id).body)
        self.assertEqual(len(result['proxies']), 5)
        self.assertEqual(len(schema.links), 3)
        self.assertEqual((self.inbounds, self.hosts), original)
        user.portal_account.proxy_user = None
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(UserResponse.model_validate(user).local_node_selections, {})

    def test_group_members_only_reference_the_filtered_nodes(self):
        plan = self.make_plan(local_node_selections=self.selection,
                              group_members={'🚀 节点选择': ['inbound:XHTTP', 'inbound:VISION']})
        user = self.subscribe(plan)
        result = yaml.safe_load(build_subscription_response(UserResponse.model_validate(user), client_type='clash-meta', db=self.db, user_id=user.id).body)
        members = next(group for group in result['proxy-groups'] if group['name'] == '🚀 节点选择')['proxies']
        self.assertEqual(len(members), 3)
        self.assertTrue(all(member.startswith('[ipv6] ') for member in members))

    def test_catalog_requires_sudo(self):
        from tests.test_private_external_subscriptions import PrivateExternalTests
        from app.db import crud
        from app.models.admin import AdminCreate
        from app.utils.jwt import create_admin_token
        def database():
            with self.Session() as db: yield db
        app.dependency_overrides[get_db] = database
        self.addCleanup(app.dependency_overrides.pop, get_db)
        admin = crud.create_admin(self.db, AdminCreate(username='route-admin', password='test-only', is_sudo=False))
        with patch('app.utils.jwt.get_secret_key', return_value='route-test-secret'):
            token = create_admin_token(admin.username, False)
            self.assertIn(PrivateExternalTests.request(self, 'GET', '/api/commerce/admin/local-node-catalog').status, (401, 403))
            self.assertEqual(PrivateExternalTests.request(self, 'GET', '/api/commerce/admin/local-node-catalog', token=token).status, 403)

    def test_admin_save_reload_applies_to_existing_subscriber_without_core_update(self):
        from app.models.admin import Admin
        plan = self.make_plan()
        user = self.subscribe(plan)
        identity = copy.deepcopy(user.proxies[0].settings)
        background = BackgroundTasks()
        updated = commerce_router.admin_update_plan(
            plan.id, SubscriptionPlanUpdate(local_node_selections=self.selection), background,
            self.db, Admin(username='test', is_sudo=True))
        self.assertEqual(updated.local_node_selections, self.selection)
        self.assertEqual(background.tasks, [])
        self.db.expire_all()
        self.assertEqual(user.proxies[0].settings, identity)
        schema = UserResponse.model_validate(user)
        self.assertEqual(schema.local_node_selections, self.selection)
        self.assertEqual(len(schema.links), 1)

    def test_nullable_migration_preserves_existing_plan_entitlements(self):
        migration = importlib.import_module('app.db.migrations.versions.c64e3fb07221_plan_local_node_selections')
        with self.engine.begin() as connection:
            # Exercise the real migration on a minimal legacy table in an isolated database.
            connection.execute(sa.text('ALTER TABLE subscription_plans DROP COLUMN local_node_selections'))
            connection.execute(sa.text("INSERT INTO subscription_plans (name, price_minor, duration_days, data_limit, inbound_tags, is_visible, created_at, updated_at) VALUES ('legacy', 0, 30, 0, '[\"VISION\"]', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            operations = Operations(MigrationContext.configure(connection))
            with patch.object(migration, 'op', operations):
                migration.upgrade()
            row = connection.execute(sa.text('SELECT inbound_tags, local_node_selections FROM subscription_plans')).one()
            self.assertEqual(json.loads(row[0]), ['VISION'])
            self.assertIsNone(row[1])
        plan = self.db.query(SubscriptionPlan).one()
        self.assertEqual(SubscriptionPlanResponse.model_validate(plan).local_node_selections, {})

    def test_save_prunes_deleted_inbound_and_group_references_without_blocking_edit(self):
        from app.models.admin import Admin
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        identity = copy.deepcopy(user.proxies[0].settings)
        plan.inbound_tags = [*plan.inbound_tags, 'REMOVED']
        plan.local_node_selections = {**self.selection, 'REMOVED': ['f' * 64]}
        plan.group_members = {'🚀 节点选择': ['inbound:REMOVED', 'inbound:VISION'],
                              'REMOVED GROUP': ['inbound:VISION']}
        self.db.commit()
        background = BackgroundTasks()
        commerce_router.admin_update_plan(plan.id, SubscriptionPlanUpdate(description='now editable'),
                                          background, self.db, Admin(username='test', is_sudo=True))
        self.assertEqual(plan.inbound_tags, ['VISION', 'XHTTP'])
        self.assertEqual(plan.local_node_selections, self.selection)
        self.assertEqual(plan.group_members, {'🚀 节点选择': ['inbound:VISION']})
        self.assertEqual(plan.description, 'now editable')
        self.assertEqual(len(background.tasks), 1)
        self.assertEqual(user.proxies[0].settings, identity)

    def test_save_prunes_stale_payload_and_keeps_empty_group_explicit(self):
        plan = self.make_plan(local_node_selections=self.selection)
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(
            inbound_tags=['VISION', 'REMOVED'],
            local_node_selections={**self.selection, 'REMOVED': ['f' * 64]},
            group_members={'🚀 节点选择': ['inbound:REMOVED']}))
        self.assertEqual(plan.inbound_tags, ['VISION'])
        self.assertEqual(plan.local_node_selections, {'VISION': self.selection['VISION']})
        self.assertEqual(plan.group_members, {'🚀 节点选择': []})

    def test_cleanup_removes_only_stale_profiles_without_authorizing_new_routes(self):
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        self.inbounds['XHTTP']['xhttpProfiles'].pop(1)
        changed, users = commerce.cleanup_plan_local_nodes(self.db, plan.id)
        self.assertTrue(changed)
        self.assertEqual(users, [])
        self.assertEqual(plan.local_node_selections['XHTTP'], self.selection['XHTTP'][1:])
        result = yaml.safe_load(build_subscription_response(UserResponse.model_validate(user), client_type='clash-meta', db=self.db, user_id=user.id).body)
        self.assertEqual(len(result['proxies']), 2)
        self.assertTrue(all(node['name'].startswith('[ipv6] ') for node in result['proxies']))

    def test_cleanup_last_custom_profile_removes_inbound_and_preserves_purchase_facts(self):
        from app.db.models import PortalPurchase
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        purchase = self.db.query(PortalPurchase).one()
        facts = (purchase.inbound_tags[:], purchase.duration_days, purchase.data_limit,
                 user.proxies[0].settings.copy(), user.used_traffic, user.expire)
        self.inbounds['XHTTP']['xhttpProfiles'] = self.inbounds['XHTTP']['xhttpProfiles'][:1]
        changed, affected = commerce.cleanup_plan_local_nodes(self.db, plan.id)
        self.assertTrue(changed)
        self.assertEqual([value[0] for value in affected], [user.id])
        self.assertEqual(plan.inbound_tags, ['VISION'])
        self.assertEqual(plan.local_node_selections, {'VISION': self.selection['VISION']})
        self.assertEqual(user.inbounds[ProxyTypes.VLESS], ['VISION'])
        self.assertEqual(user.portal_account.subscription.inbound_tags, ['VISION'])
        self.assertEqual((purchase.inbound_tags, purchase.duration_days, purchase.data_limit,
                          user.proxies[0].settings, user.used_traffic, user.expire), facts)

    def test_fully_empty_plan_is_hidden_editable_and_cannot_be_granted(self):
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        self.hosts['VISION'].pop(1)
        self.inbounds['XHTTP']['xhttpProfiles'] = self.inbounds['XHTTP']['xhttpProfiles'][:1]
        commerce.cleanup_plan_local_nodes(self.db, plan.id)
        self.assertEqual(plan.inbound_tags, [])
        self.assertEqual(plan.local_node_selections, {})
        self.assertFalse(plan.is_visible)
        self.assertEqual(user.inbounds[ProxyTypes.VLESS], [])
        commerce.update_plan(self.db, plan, SubscriptionPlanUpdate(name='still editable', is_visible=True))
        self.assertEqual(plan.name, 'still editable')
        self.assertFalse(plan.is_visible)
        bob = self.register('bob-empty')
        with self.assertRaises(commerce.PlanConfigurationError):
            commerce.grant_plan(self.db, bob, plan, actor_admin='test', idempotency_key='empty-grant')
        self.db.rollback()

    def test_noop_cleanup_does_not_update_plan_or_subscribers(self):
        plan = self.make_plan(local_node_selections=self.selection)
        self.subscribe(plan)
        before = plan.updated_at
        self.assertEqual(commerce.cleanup_plan_local_nodes(self.db, plan.id), (False, []))
        self.assertEqual(plan.updated_at, before)

    def test_scheduled_cleanup_syncs_users_and_retries_failed_runtime_updates(self):
        from contextlib import contextmanager
        from pathlib import Path
        from app import scheduler
        from app.models.user import UserStatus
        plan = self.make_plan(local_node_selections=self.selection)
        user = self.subscribe(plan)
        user_id = user.id
        self.inbounds['XHTTP']['xhttpProfiles'] = self.inbounds['XHTTP']['xhttpProfiles'][:1]
        spec = importlib.util.spec_from_file_location('isolated_plan_cleanup_job', Path(__file__).parents[1] / 'app/jobs/plan_entitlements.py')
        job = importlib.util.module_from_spec(spec); spec.loader.exec_module(job)
        self.addCleanup(scheduler.remove_job, 'cleanup_stale_plan_nodes')
        self.assertEqual(scheduler.get_job('cleanup_stale_plan_nodes').trigger.interval.total_seconds(), 300)
        @contextmanager
        def database():
            with self.Session() as db: yield db
        with patch.object(job, 'GetDB', database), patch.object(xray.operations, 'update_user_by_id', side_effect=RuntimeError('transient')) as update:
            job.cleanup_stale_plan_nodes()
        update.assert_called_once_with(user_id=user_id)
        self.assertEqual(job._pending_users, {user_id})
        self.db.expire_all(); user.status = UserStatus.disabled; self.db.commit()
        with patch.object(job, 'GetDB', database), patch.object(xray.operations, 'remove_user_by_id') as remove:
            job.cleanup_stale_plan_nodes()
        remove.assert_called_once_with(user_id=user_id)
        self.assertFalse(job._pending_users)
