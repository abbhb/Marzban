"""Panel-owned rules, separate from untrusted external node overlays."""
import copy
import re
from ipaddress import ip_network
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.db.models import SubscriptionRules
from app.subscription.clash import ClashConfiguration, CLASH_RESERVED_PROXY_NAMES


class RulesUpdate(BaseModel):
    rules: Optional[list[str]] = Field(default=None, max_length=10000)
    revision: int = Field(ge=0)


class RulesConflict(Exception):
    pass


def template_document():
    return yaml.safe_load(ClashConfiguration().render())


def read_rules(db):
    document = template_document()
    saved = db.get(SubscriptionRules, 1)
    rules = saved.rules if saved is not None and saved.rules is not None else document.get("rules", [])
    return {
        "rules": rules,
        "enabled": saved is not None and saved.rules is not None,
        "revision": saved.revision if saved is not None else 0,
        "targets": sorted(set(CLASH_RESERVED_PROXY_NAMES) | {
            group["name"] for group in document.get("proxy-groups", [])
            if isinstance(group, dict) and isinstance(group.get("name"), str)
        }),
        "providers": sorted(document.get("rule-providers", {})),
    }


def validate_rules(rules, document):
    if rules is None:
        return
    if not rules or sum(len(rule) for rule in rules) > 1000000:
        raise ValueError("Rules must contain 1–10000 lines and at most 1 MB of text")
    targets = set(CLASH_RESERVED_PROXY_NAMES) | {
        group["name"] for group in document.get("proxy-groups", [])
        if isinstance(group, dict) and isinstance(group.get("name"), str)
    }
    providers = document.get("rule-providers", {})
    for number, rule in enumerate(rules, 1):
        if len(rule) > 8192 or any(char in rule for char in "\r\n\x00"):
            raise ValueError(f"Line {number}: invalid rule text")
        parts = [part.strip() for part in rule.split(",")]
        rule_type = parts[0]
        # Logical rules contain nested commas; policy is still the last field.
        policy_index = -2 if parts[-1] == "no-resolve" else -1
        minimum = 2 if rule_type == "MATCH" else 3
        if len(parts) < minimum or not all(parts):
            raise ValueError(f"Line {number}: expected TYPE,value,target or MATCH,target")
        if rule_type not in {
            "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX", "GEOSITE",
            "IP-CIDR", "IP-CIDR6", "IP-SUFFIX", "IP-ASN", "GEOIP", "SRC-GEOIP",
            "SRC-IP-ASN", "SRC-IP-CIDR", "SRC-IP-SUFFIX", "DST-PORT", "SRC-PORT",
            "IN-PORT", "IN-TYPE", "IN-USER", "IN-NAME", "PROCESS-PATH",
            "PROCESS-PATH-REGEX", "PROCESS-NAME", "PROCESS-NAME-REGEX", "UID",
            "NETWORK", "DSCP", "RULE-SET", "AND", "OR", "NOT", "MATCH",
        }:
            raise ValueError(f"Line {number}: unsupported rule type {rule_type}")
        expected_parts = minimum + (1 if parts[-1] == "no-resolve" else 0)
        if rule_type not in {"AND", "OR", "NOT"} and len(parts) != expected_parts:
            raise ValueError(f"Line {number}: unexpected rule fields")
        if rule_type in {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"}:
            try:
                network = ip_network(parts[1], strict=False)
            except ValueError:
                raise ValueError(f"Line {number}: invalid IP network") from None
            if rule_type == "IP-CIDR6" and network.version != 6:
                raise ValueError(f"Line {number}: IP-CIDR6 requires IPv6")
        if rule_type in {"DST-PORT", "SRC-PORT", "IN-PORT"}:
            ports = parts[1].split("-")
            if (len(ports) > 2 or any(not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535 for port in ports)
                    or (len(ports) == 2 and int(ports[0]) > int(ports[1]))):
                raise ValueError(f"Line {number}: invalid port or port range")
        if rule_type in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"} and re.search(r"\s", parts[1]):
            raise ValueError(f"Line {number}: domain must not contain whitespace")
        if parts[policy_index] not in targets:
            raise ValueError(f"Line {number}: unknown target {parts[policy_index]}")
        if rule_type == "RULE-SET" and parts[1] not in providers:
            raise ValueError(f"Line {number}: unknown rule provider {parts[1]}")
        if rule_type == "MATCH" and (number != len(rules) or len(parts) != 2):
            raise ValueError(f"Line {number}: MATCH must be the final rule")
    if not rules[-1].startswith("MATCH,"):
        raise ValueError("The final rule must be MATCH,target")


def save_rules(db, values):
    validate_rules(values.rules, template_document())
    try:
        if values.revision == 0:
            db.add(SubscriptionRules(id=1, rules=values.rules, revision=1))
            db.flush()
        else:
            result = db.execute(update(SubscriptionRules).where(
                SubscriptionRules.id == 1,
                SubscriptionRules.revision == values.revision,
            ).values(rules=values.rules, revision=values.revision + 1))
            if result.rowcount != 1:
                raise RulesConflict()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RulesConflict() from None
    except Exception:
        db.rollback()
        raise
    db.expire_all()
    return read_rules(db)


def load_rules(db):
    saved = db.get(SubscriptionRules, 1)
    return copy.deepcopy(saved.rules) if saved is not None else None
