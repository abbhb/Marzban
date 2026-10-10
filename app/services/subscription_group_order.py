"""Order template policy groups without admitting external groups into the policy."""
import copy

from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.db.models import SubscriptionGroupOrder
from app.services.subscription_rules import template_document
from app.subscription.clash import EXTERNAL_AGGREGATE_GROUP_NAME, ordered_template_groups


class GroupOrderUpdate(BaseModel):
    group_names: list[str] | None = Field(default=None, max_length=2048)
    revision: int = Field(ge=0)


class GroupOrderConflict(Exception):
    pass


def template_group_names(document):
    return list(dict.fromkeys(
        group["name"] for group in document.get("proxy-groups", [])
        if isinstance(group, dict) and isinstance(group.get("name"), str)
        and group["name"] != EXTERNAL_AGGREGATE_GROUP_NAME
    ))


def read_group_order(db):
    document = template_document()
    saved = db.get(SubscriptionGroupOrder, 1)
    names = saved.group_names if saved else None
    return {
        "group_names": template_group_names({"proxy-groups": ordered_template_groups(document.get("proxy-groups", []), names)}),
        "template_group_names": template_group_names(document),
        "enabled": names is not None,
        "revision": saved.revision if saved else 0,
        "fixed_external_group": EXTERNAL_AGGREGATE_GROUP_NAME,
    }


def save_group_order(db, values):
    if values.group_names is not None:
        expected = template_group_names(template_document())
        if len(values.group_names) != len(expected) or set(values.group_names) != set(expected):
            raise ValueError("Include each current template group exactly once. External groups are fixed at the bottom; reload the group list before saving.")
    try:
        if values.revision == 0:
            db.add(SubscriptionGroupOrder(id=1, group_names=values.group_names, revision=1))
            db.flush()
        else:
            result = db.execute(update(SubscriptionGroupOrder).where(
                SubscriptionGroupOrder.id == 1,
                SubscriptionGroupOrder.revision == values.revision,
            ).values(group_names=values.group_names, revision=values.revision + 1))
            if result.rowcount != 1:
                raise GroupOrderConflict()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GroupOrderConflict() from None
    except Exception:
        db.rollback()
        raise
    db.expire_all()
    return read_group_order(db)


def load_group_order(db):
    saved = db.get(SubscriptionGroupOrder, 1)
    return copy.deepcopy(saved.group_names) if saved else None
