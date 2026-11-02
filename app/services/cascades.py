"""Panel-owned, two-hop Mihomo routes. Upstream references stay untrusted."""
from textwrap import indent

import yaml

from app import xray
from app.db.models import ExternalSubscriptionNode, ExternalSubscriptionSource
from app.services import external_subscriptions as external
from app.subscription.local_nodes import selected_route


class CascadeError(ValueError):
    """A credential-free error safe to return to administrators."""


def _has_reference(value):
    if isinstance(value, dict):
        return any(key in external._UPSTREAM_REFERENCE_KEYS or _has_reference(child)
                   for key, child in value.items())
    if isinstance(value, list):
        return any(_has_reference(child) for child in value)
    return False


def parse_entry_yaml(value: str) -> dict:
    """Accept one node mapping, one list item, or a one-node Clash document."""
    if not value or len(value.encode("utf-8")) > 32768:
        raise CascadeError("cascade_invalid_yaml")
    text = value.strip().lstrip("\ufeff")
    candidates = (text, "proxies:\n" + indent(text, "  "),
                  "proxies:\n  -\n" + indent(text, "    "))
    for candidate in candidates:
        try:
            snapshot = external.parse_clash_subscription(candidate.encode("utf-8"))
        except external.ExternalSubscriptionParseError:
            continue
        if len(snapshot.nodes) == 1 and snapshot.skipped_node_count == 0:
            payload = snapshot.nodes[0].payload
            if not _has_reference(payload):
                return payload
    raise CascadeError("cascade_invalid_yaml")


def external_entry(db, node_id: int):
    node = db.get(ExternalSubscriptionNode, node_id)
    if (node is None or not node.is_active or node.source is None or node.source.owner_account_id is not None
            or not node.source.enabled):
        raise CascadeError("cascade_entry_unavailable")
    return node


def validate_hosts(db, hosts_by_tag):
    if any(host.cascade_mode != "off" and host.cascade_entry_id
           for hosts in hosts_by_tag.values() for host in hosts):
        # Serialize new references with refresh's tombstone/deletion decision.
        external.lock_external_budget_for_update(db)
    for hosts in hosts_by_tag.values():
        for host in hosts:
            if host.cascade_mode == "off":
                continue
            if bool(host.cascade_entry_id) == bool(host.cascade_entry_yaml):
                raise CascadeError("cascade_choose_one_entry")
            if host.cascade_entry_id:
                node = external_entry(db, host.cascade_entry_id)
                external.decrypt_proxy_payload(node.payload_ciphertext)
            else:
                # Check encryption availability before any host is changed.
                external.encrypt_proxy_payload(parse_entry_yaml(host.cascade_entry_yaml))


def entry_choices(db, search: str = "", selected_id: int | None = None):
    query = db.query(ExternalSubscriptionNode).join(ExternalSubscriptionSource).filter(
        ExternalSubscriptionNode.is_active.is_(True),
        ExternalSubscriptionSource.owner_account_id.is_(None),
        ExternalSubscriptionSource.enabled.is_(True),
    )
    if search:
        query = query.filter(ExternalSubscriptionNode.name.ilike(f"%{search}%"))
    nodes = query.order_by(ExternalSubscriptionNode.source_id, ExternalSubscriptionNode.position).limit(100).all()
    if selected_id and all(n.id != selected_id for n in nodes):
        try:
            nodes.insert(0, external_entry(db, selected_id))
        except CascadeError:
            pass
    return [{"id": n.id, "name": n.name, "source": n.source.name, "type": n.proxy_type} for n in nodes]


def resolve_for_user(db, user, config_format: str) -> dict[int, dict]:
    """Resolve only entitled hosts, at request time so refreshes take effect."""
    from app.db.models import ProxyHost
    tags = {tag for values in user.inbounds.values() for tag in values}
    if not tags:
        return {}
    rows = db.query(ProxyHost).filter(ProxyHost.inbound_tag.in_(tags),
                                    ProxyHost.cascade_mode != "off", ProxyHost.is_disabled.is_(False)).all()
    rows_by_id = {row.id: row for row in rows}
    result = {}
    selections = getattr(user, "local_node_selections", {}) or {}
    for tag in tags:
        inbound = xray.config.inbounds_by_tag.get(tag)
        if not inbound:
            continue
        for host in xray.hosts.get(tag, []):
            row = rows_by_id.get(host.get("id"))
            if row is None or selected_route(host, inbound, selections.get(tag)) is None:
                continue
            if config_format != "clash-meta":
                raise CascadeError("cascade_requires_mihomo")
            try:
                if row.cascade_entry_id:
                    node = external_entry(db, row.cascade_entry_id)
                    payload = external.decrypt_proxy_payload(node.payload_ciphertext)
                else:
                    if not row.cascade_entry_ciphertext:
                        raise CascadeError("cascade_entry_unavailable")
                    payload = external.decrypt_proxy_payload(row.cascade_entry_ciphertext)
                # Apply the same bounded parser after decryption as on import.
                result[row.id] = parse_entry_yaml(yaml.safe_dump(payload, allow_unicode=True))
            except (external.ExternalSubscriptionError, CascadeError):
                raise CascadeError("cascade_entry_unavailable") from None
    return result
