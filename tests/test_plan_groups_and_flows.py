import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import yaml
from fastapi import HTTPException

from app.db.models import SubscriptionPlan
from app.services import plan_groups
from app.subscription.clash import ClashConfiguration, ClashMetaConfiguration, EXTERNAL_AGGREGATE_GROUP_NAME
from app.subscription.shadowrocket import prepare_shadowrocket
from app.xray.flow import settings_for_inbound, VISION
from app.routers import core
from app.xray.config import XRayConfig
from app.xray import operations
from app import xray
from app import app
from app.db import crud, get_db
from app.models.admin import AdminCreate
from app.utils.jwt import create_admin_token
from app.models.proxy import ProxyTypes
from tests.test_mgma import MgmaDatabaseTestCase


class PlanGroupsAndFlowsTests(MgmaDatabaseTestCase):
    def request(self, *args, **kwargs):
        from tests.test_private_external_subscriptions import PrivateExternalTests
        return PrivateExternalTests.request(self, *args, **kwargs)

    def test_new_admin_endpoints_require_sudo(self):
        def database():
            with self.Session() as db: yield db
        app.dependency_overrides[get_db]=database
        self.addCleanup(app.dependency_overrides.pop,get_db)
        admin=crud.create_admin(self.db,AdminCreate(username='flow-limited',password='test-only',is_sudo=False))
        with patch('app.utils.jwt.get_secret_key',return_value='test-flow-secret'):
            token=create_admin_token(admin.username,False)
            for path in ('/api/core/inbound-flows','/api/commerce/admin/group-catalog'):
                with self.subTest(path=path):
                    self.assertIn(self.request('GET',path).status,(401,403))
                    self.assertEqual(self.request('GET',path,token=token).status,403)
            self.assertEqual(self.request('PUT','/api/core/inbound-flows',token=token,payload={'revision':'test','flows':{}}).status,403)

    def test_plan_groups_persist_and_reject_unowned_or_external_node_references(self):
        with patch.object(plan_groups, 'group_catalog', return_value=['AI', 'Claude']):
            valid={'AI':['inbound:US02', 'external'], 'Claude':[]}
            plan_groups.validate_members(valid,['US02'])
            for groups in ({'AI':['inbound:SECRET']}, {'AI':['MGMA-EXT private']},
                           {'AI':['external','external']}, {EXTERNAL_AGGREGATE_GROUP_NAME:[]}, {'missing':[]}):
                with self.subTest(groups=groups), self.assertRaises(ValueError):
                    plan_groups.validate_members(groups,['US02'])
        p=SubscriptionPlan(name='arranged',price_minor=0,duration_days=30,data_limit=0,
                           inbound_tags=['US02'],group_members=valid)
        self.db.add(p); self.db.commit(); self.db.expire_all()
        self.assertEqual(self.db.get(SubscriptionPlan,p.id).group_members,valid)

    def test_export_members_are_ordered_authorized_and_never_expose_external_nodes(self):
        document={'proxies':[{'name':'US 02','type':'vless'},{'name':'MGMA-EXT private','type':'ss'}],
                  'proxy-groups':[{'name':'AI','type':'select','include-all-proxies':True,'filter':'.*'},
                                  {'name':'Claude','type':'select','proxies':['DIRECT']},
                                  {'name':EXTERNAL_AGGREGATE_GROUP_NAME,'type':'select','proxies':['Airport']},
                                  {'name':'Airport','type':'select','proxies':['MGMA-EXT private']}]}
        groups={'AI':['external','inbound:US02','inbound:NOT_GRANTED'],'Claude':['inbound:NOT_GRANTED']}
        result=plan_groups.apply_members(copy.deepcopy(document),groups,{'US02':['US 02']})
        self.assertEqual(result['proxy-groups'][0]['proxies'],[EXTERNAL_AGGREGATE_GROUP_NAME,'US 02'])
        self.assertNotIn('include-all-proxies',result['proxy-groups'][0])
        self.assertEqual(result['proxy-groups'][1]['proxies'],['REJECT'])
        self.assertEqual(prepare_shadowrocket(result)['proxy-groups'][0]['proxies'],[EXTERNAL_AGGREGATE_GROUP_NAME,'US 02'])
        result['proxy-groups']=result['proxy-groups'][:2]
        self.assertEqual(plan_groups.apply_members(result,{'AI':['external']},{})['proxy-groups'][0]['proxies'],['REJECT'])

    def test_renderer_applies_members_after_external_merge(self):
        document={'proxies':[{'name':'US02','type':'ss','server':'public.example','port':443,'cipher':'aes-128-gcm','password':'test'}],
                  'proxy-groups':[{'name':'AI','type':'select','proxies':['DIRECT']}], 'rules':['MATCH,AI']}
        for meta in (False,True):
            with patch('app.subscription.clash.render_template',side_effect=lambda name,context=None:
                       yaml.safe_dump(document) if name=='clash/default.yml' else '{}'):
                c=ClashConfiguration(); c.inbound_proxy_names={'US':['US02']}
                result=yaml.safe_load(c.render(is_meta=meta,plan_group_members={'AI':['inbound:US']}))
                self.assertEqual(result['proxy-groups'][0]['proxies'],['US02'])

    def test_flow_is_scoped_and_input_settings_are_never_modified(self):
        user={'id':'test','flow':''}
        base={'protocol':'vless','network':'tcp','tls':'reality','header_type':''}
        self.assertEqual(settings_for_inbound(user,{**base,'flow_override':VISION})['flow'],VISION)
        self.assertEqual(settings_for_inbound(user,base)['flow'],'')
        self.assertEqual(settings_for_inbound({'flow':VISION},{**base,'flow_override':''})['flow'],'')
        self.assertEqual(settings_for_inbound(user,{**base,'network':'ws','flow_override':VISION})['flow'],'')
        self.assertEqual(user,{'id':'test','flow':''})
        c=ClashMetaConfiguration()
        c.add('US02','public.example',{**base,'port':443,'sni':'www.bing.com','host':'','path':''},{'id':'test-only','flow':VISION})
        self.assertEqual(c.data['proxies'][0]['packet-encoding'],'xudp')

    def test_flow_endpoint_rejects_stale_or_incompatible_settings_without_reloading(self):
        document={'inbounds':[{'tag':'US','protocol':'vless'}]}
        with patch.object(core,'_flow_document',return_value=document), patch.object(core,'modify_core_config') as save:
            with self.assertRaises(HTTPException) as error:
                core.put_inbound_flows(core.InboundFlowsUpdate(revision='old',flows={'US':VISION}),MagicMock())
            self.assertEqual(error.exception.status_code,409)
            with patch.object(core.xray.config,'inbounds_by_tag',{'US':{'protocol':'vless','network':'ws','tls':'reality'}}):
                with self.assertRaises(HTTPException):
                    core.put_inbound_flows(core.InboundFlowsUpdate(revision=core._flow_revision(document),flows={'US':VISION}),MagicMock())
            save.assert_not_called()

    def test_startup_dynamic_updates_and_subscription_use_the_same_inbound_flows(self):
        user=self.create_user()
        raw={'inbounds':[
            {'tag':tag,'port':port,'protocol':'vless','settings':{'clients':[],'decryption':'none'},
             'streamSettings':{'network':'tcp','security':'tls','tlsSettings':{}},
             **({'x-marzban-flow':VISION} if tag=='US02' else {})}
            for tag,port in [('LEGACY',12345),('US02',12346)]],
             'outbounds':[{'tag':'DIRECT','protocol':'freedom'}]}
        config=XRayConfig(raw)
        @contextmanager
        def database(): yield self.db
        with patch('app.xray.config.GetDB',database):
            populated=config.include_db_users()
        for tag,expected in [('LEGACY',''),('US02',VISION)]:
            self.assertEqual(populated.get_inbound(tag)['settings']['clients'][0].get('flow',''),expected)
        response=SimpleNamespace(inbounds={ProxyTypes.VLESS:['LEGACY','US02']},proxies={ProxyTypes.VLESS:MagicMock()})
        response.proxies[ProxyTypes.VLESS].dict.return_value={'id':user.proxies[0].settings['id'],'flow':''}
        with patch.object(xray,'config',config),patch.object(xray,'nodes',{}),patch.object(operations.UserResponse,'model_validate',return_value=response),patch.object(operations,'_alter_inbound_user') as alter:
            operations.update_user(user)
            self.assertEqual([(call.args[1],call.args[2].flow.value) for call in alter.call_args_list], [('LEGACY',''),('US02',VISION)])
        from app.subscription.share import process_inbounds_and_tags
        captured=[]
        fake=SimpleNamespace(add=lambda **kw:captured.append(kw),render=lambda **kw:'ok')
        response.proxies[ProxyTypes.VLESS].model_dump.return_value={'id':'test','flow':''}
        hosts={tag:[{'sni':[],'host':[],'address':['public.example'],'path':None,'port':None,'tls':None,'alpn':None,'fingerprint':None,'allowinsecure':None,'mux_enable':False,'fragment_setting':None,'noise_setting':None,'random_user_agent':False,'remark':tag}] for tag in ('LEGACY','US02')}
        with patch.object(xray,'config',config),patch.object(xray,'hosts',hosts):
            process_inbounds_and_tags(response.inbounds,response.proxies,{},fake)
        self.assertEqual([c['settings']['flow'] for c in captured],['',VISION])
