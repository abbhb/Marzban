"""Plan-owned group members; references never grant access to proxy nodes."""
import copy

from app.db.models import PortalAccount, PortalSubscription, SubscriptionPlan
from app.services.subscription_rules import template_document
from app.subscription.clash import EXTERNAL_AGGREGATE_GROUP_NAME

EXTERNAL = "external"
PREFIX = "inbound:"


def group_catalog():
    return [g["name"] for g in template_document().get("proxy-groups", [])
            if isinstance(g, dict) and isinstance(g.get("name"), str)
            and g["name"] != EXTERNAL_AGGREGATE_GROUP_NAME]


def validate_members(groups, inbound_tags):
    if not isinstance(groups, dict) or len(groups) > 64:
        raise ValueError("Group membership must contain at most 64 groups")
    names = set(group_catalog())
    allowed = {EXTERNAL} | {PREFIX + tag for tag in inbound_tags}
    for name, members in groups.items():
        if name not in names:
            raise ValueError("Unknown policy group; reload the editor")
        if (not isinstance(members, list) or len(members) > 128
                or any(not isinstance(m, str) or m not in allowed for m in members)
                or len(members) != len(set(members))):
            raise ValueError("Only unique plan inbounds and MGMA · External may be arranged")


def load_for_user(db, user_id):
    plan = (db.query(SubscriptionPlan)
            .join(PortalSubscription, PortalSubscription.plan_id == SubscriptionPlan.id)
            .join(PortalAccount, PortalAccount.id == PortalSubscription.account_id)
            .filter(PortalAccount.user_id == user_id).first())
    return copy.deepcopy(plan.group_members or {}) if plan else {}


def apply_members(document, groups, node_names):
    """Use only nodes rendered for this user, after external isolation/merge."""
    known = {p["name"] for p in document.get("proxies", [])}
    external = next((g for g in document.get("proxy-groups", [])
                     if g.get("name") == EXTERNAL_AGGREGATE_GROUP_NAME), None)
    for group in document.get("proxy-groups", []):
        if group.get("name") == EXTERNAL_AGGREGATE_GROUP_NAME or group.get("name") not in groups:
            continue
        selected = []
        for ref in groups[group["name"]]:
            candidates = ([EXTERNAL_AGGREGATE_GROUP_NAME] if ref == EXTERNAL and external else
                          node_names.get(ref[len(PREFIX):], []) if ref.startswith(PREFIX) else [])
            for name in candidates:
                if (name in known or name == EXTERNAL_AGGREGATE_GROUP_NAME) and name not in selected:
                    selected.append(name)
        # Empty/unavailable choices must not silently fall back to direct access.
        for key in ("include-all", "include-all-proxies", "include-all-providers", "filter", "exclude-filter", "exclude-type", "use"):
            group.pop(key, None)
        group["proxies"] = selected or ["REJECT"]
    return document
