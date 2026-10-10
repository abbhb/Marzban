"""Persistent panel rule policy, optimistic writes and subscription integration."""
import unittest
from unittest.mock import patch

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.services import subscription_rules as rules
from app.subscription.clash import ClashConfiguration
from tests.test_mgma import MgmaDatabaseTestCase
from app.models.user import UserResponse
from app.routers.subscription import build_subscription_response

DOCUMENT = {
    "mode": "global", "rules": ["MATCH,DIRECT"],
    "proxy-groups": [{"name": "Proxy", "type": "select", "proxies": ["DIRECT"]}],
    "rule-providers": {"ads": {}},
}


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.template = patch.object(rules, "template_document", return_value=DOCUMENT)
        self.template.start()
        self.addCleanup(self.template.stop)

    def test_save_refresh_conflict_and_restore(self):
        initial = rules.read_rules(self.db)
        self.assertFalse(initial["enabled"])
        updated = rules.save_rules(self.db, rules.RulesUpdate(
            rules=["DOMAIN-SUFFIX,example.com,Proxy", "MATCH,DIRECT"], revision=0))
        self.assertEqual(updated["revision"], 1)
        self.assertTrue(updated["enabled"])
        with self.assertRaises(rules.RulesConflict):
            rules.save_rules(self.db, rules.RulesUpdate(rules=["MATCH,REJECT"], revision=0))
        self.assertEqual(rules.read_rules(self.db)["rules"], updated["rules"])
        restored = rules.save_rules(self.db, rules.RulesUpdate(rules=None, revision=1))
        self.assertFalse(restored["enabled"])
        self.assertEqual(restored["rules"], DOCUMENT["rules"])
        self.assertIsNone(rules.load_rules(self.db))

    def test_invalid_rules_leave_previous_policy_intact(self):
        rules.save_rules(self.db, rules.RulesUpdate(rules=["MATCH,DIRECT"], revision=0))
        for value in [[], ["MATCH,Missing"], ["MATCH,DIRECT", "DOMAIN,a,Proxy"],
                      ["DOMAIN,a,Proxy"], ["RULE-SET,missing,Proxy", "MATCH,DIRECT"],
                      ["INVALID,a,Proxy", "MATCH,DIRECT"], ["IP-CIDR,broken,Proxy", "MATCH,DIRECT"],
                      ["DST-PORT,65536,Proxy", "MATCH,DIRECT"], ["DOMAIN,a,Proxy\nMATCH,DIRECT"]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rules.save_rules(self.db, rules.RulesUpdate(rules=value, revision=1))
            self.assertEqual(rules.load_rules(self.db), ["MATCH,DIRECT"])

    def test_rules_override_changes_mode_and_preserves_template_configuration(self):
        with patch("app.subscription.clash.render_template", side_effect=lambda name, context=None:
                   '{}' if name != 'clash/default.yml' else yaml.safe_dump(DOCUMENT)):
            config = ClashConfiguration()
            result = yaml.safe_load(config.render(subscription_rules=["MATCH,REJECT"]))
        self.assertEqual(result["rules"], ["MATCH,REJECT"])
        self.assertEqual(result["mode"], "rule")
        self.assertEqual(result["proxy-groups"], DOCUMENT["proxy-groups"])
        self.assertEqual(result["rule-providers"], DOCUMENT["rule-providers"])


class SubscriptionRuleIntegrationTests(MgmaDatabaseTestCase):
    def test_all_supported_subscription_formats_receive_persisted_rules(self):
        user = self.create_user()
        with patch.object(rules, "template_document", return_value=DOCUMENT):
            rules.save_rules(self.db, rules.RulesUpdate(rules=["MATCH,REJECT"], revision=0))
        for client in ("clash", "clash-meta", "shadowrocket"):
            with self.subTest(client=client), patch(
                "app.routers.subscription.load_external_overlays_for_user", return_value=[]
            ), patch(
                "app.subscription.clash.render_template", side_effect=lambda name, context=None:
                '{}' if name != 'clash/default.yml' else yaml.safe_dump(DOCUMENT)
            ):
                response = build_subscription_response(
                    UserResponse.model_validate(user), client_type=client,
                    db=self.db, user_id=user.id)
                result = yaml.safe_load(response.body)
                self.assertEqual(result["rules"], ["MATCH,REJECT"])
                self.assertEqual(result["mode"], "rule")
