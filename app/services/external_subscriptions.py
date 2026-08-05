"""Encrypted external Clash subscriptions with last-known-good refreshes."""

from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import math
import os
import secrets
import socket
import ssl
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import (
    AliasToken,
    AnchorToken,
    BlockEndToken,
    BlockMappingStartToken,
    BlockSequenceStartToken,
    FlowMappingEndToken,
    FlowMappingStartToken,
    FlowSequenceEndToken,
    FlowSequenceStartToken,
)

from app import logger
from app.db import Session
from app.db.models import (
    ExternalSubscriptionBudgetLock,
    ExternalSubscriptionNode,
    ExternalSubscriptionSource,
    PortalAccount,
    PortalSubscription,
    SubscriptionPlan,
    SubscriptionPlanExternalSelection,
    plan_external_selected_nodes,
)
from app.subscription.external_policy import (
    EXTERNAL_PROXY_TYPE_RE,
    MIHOMO_EXTERNAL_PROXY_TYPES,
)


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_NODES = 1000
MAX_YAML_DEPTH = 16
MAX_YAML_ITEMS = 50_000
MAX_YAML_TOKENS = 100_000
MAX_YAML_STRING_BYTES = 64 * 1024
MAX_NODE_JSON_BYTES = 256 * 1024
MAX_OVERLAY_NODES = 5000
MAX_OVERLAY_DECRYPTED_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
FETCH_DEADLINE_SECONDS = 10.0
REFRESH_LEASE_SECONDS = 60
MIN_REFRESH_INTERVAL_MINUTES = 15
DEFAULT_REFRESH_INTERVAL_MINUTES = 360
# Mihomo sends this product token when it downloads proxy providers.  Keep the
# stable prefix rather than pretending to be a particular third-party build.
# Some subscription gateways deliberately reject generic HTTP clients, so use
# this compatibility profile on the first (and only) credentialed request.
MIHOMO_COMPATIBLE_USER_AGENT = "clash.meta"
_FERNET_SALT = b"marzban/external-subscriptions/v1"
_FERNET_INFO = b"encrypted-upstream-clash-material"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_AUTH_REQUIRED_ERROR_CODES = {
    "upstream_http_401",
    "upstream_http_403",
    "upstream_http_404",
    "upstream_http_410",
}
_UPSTREAM_REFERENCE_KEYS = {
    "dialer-proxy",
    "detour",
    "outbound",
    "outbounds",
    "proxy-provider",
    "provider",
    "use",
}


class ExternalSubscriptionError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ExternalSubscriptionConfigurationError(ExternalSubscriptionError):
    pass


class ExternalSubscriptionFetchError(ExternalSubscriptionError):
    pass


class ExternalSubscriptionParseError(ExternalSubscriptionError):
    pass


@dataclass(frozen=True)
class ParsedExternalNode:
    external_key: str
    name: str
    proxy_type: str
    payload: dict[str, Any]
    position: int


@dataclass(frozen=True)
class ParsedExternalSnapshot:
    nodes: tuple[ParsedExternalNode, ...]
    skipped_node_count: int


@dataclass(frozen=True)
class FetchedExternalPayload:
    content: Optional[bytes]
    etag: Optional[str]
    last_modified: Optional[str]
    not_modified: bool = False


@dataclass(frozen=True)
class ExternalOverlaySource:
    source_id: int
    group_name: str
    nodes: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ExternalSelectionSpec:
    source_id: int
    mode: str
    node_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExternalProjectionBudget:
    node_count: int
    decrypted_bytes: int


@dataclass(frozen=True)
class ValidatedExternalURL:
    url: str
    hostname: str
    host_header: str
    request_target: str
    addresses: tuple[str, ...]


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from None
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def utc_now(value: Optional[datetime] = None) -> datetime:
    return value or datetime.utcnow()


def _fernet() -> Fernet:
    secret = os.environ.get("EXTERNAL_SUBSCRIPTION_ENCRYPTION_KEY", "")
    try:
        key_material = secret.encode("utf-8")
    except UnicodeError:
        raise ExternalSubscriptionConfigurationError(
            "encryption_key_unavailable"
        ) from None
    if len(key_material) < 32:
        raise ExternalSubscriptionConfigurationError("encryption_key_unavailable")
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_FERNET_SALT,
        info=_FERNET_INFO,
    ).derive(key_material)
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(kind: str, value: bytes) -> str:
    envelope = kind.encode("ascii") + b"\x00" + value
    return _fernet().encrypt(envelope).decode("ascii")


def _decrypt(kind: str, ciphertext: str) -> bytes:
    try:
        envelope = _fernet().decrypt(ciphertext.encode("ascii"))
    except (InvalidToken, UnicodeError, ValueError):
        raise ExternalSubscriptionConfigurationError("encrypted_data_unavailable") from None
    prefix = kind.encode("ascii") + b"\x00"
    if not envelope.startswith(prefix):
        raise ExternalSubscriptionConfigurationError("encrypted_data_unavailable")
    return envelope[len(prefix):]


def encrypt_url(url: str) -> str:
    return _encrypt("url", url.encode("utf-8"))


def decrypt_url(ciphertext: str) -> str:
    try:
        return _decrypt("url", ciphertext).decode("utf-8")
    except UnicodeError:
        raise ExternalSubscriptionConfigurationError("encrypted_data_unavailable") from None


def encrypt_proxy_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _encrypt("proxy", serialized)


def decrypt_proxy_payload(ciphertext: str) -> dict[str, Any]:
    try:
        value = json.loads(_decrypt("proxy", ciphertext))
    except (UnicodeError, ValueError, TypeError):
        raise ExternalSubscriptionConfigurationError("encrypted_data_unavailable") from None
    if not isinstance(value, dict):
        raise ExternalSubscriptionConfigurationError("encrypted_data_unavailable")
    return value


def _canonical_proxy_payload_bytes(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ExternalSubscriptionConfigurationError(
            "encrypted_data_unavailable"
        ) from None


def lock_external_budget_for_update(db: Session) -> None:
    """Acquire the global budget mutex before any source/plan row locks.

    Refreshes fetch and parse outside this short transaction.  Snapshot
    publication and plan selection edits serialize here so two sources used by
    the same plan cannot both pass against the other's previous generation.
    Keeping this as the first write lock also avoids cross-source lock cycles.
    """

    def acquire_existing() -> int:
        return (
            db.query(ExternalSubscriptionBudgetLock)
            .filter(ExternalSubscriptionBudgetLock.id == 1)
            .update(
                {
                    ExternalSubscriptionBudgetLock.version:
                        ExternalSubscriptionBudgetLock.version,
                },
                synchronize_session=False,
            )
        )

    matched = acquire_existing()
    if matched == 0:
        # Alembic seeds the singleton. Keep Base.metadata.create_all based test
        # and recovery environments safe as well. This is the first write lock
        # by contract, so rolling back an insert race cannot discard other
        # application mutations.
        try:
            db.add(ExternalSubscriptionBudgetLock(id=1, version=0))
            db.flush()
            return
        except IntegrityError:
            db.rollback()
            matched = acquire_existing()
    if matched != 1:
        db.rollback()
        raise ExternalSubscriptionConfigurationError("budget_lock_unavailable")


def lock_external_sources_for_update(
    db: Session,
    source_ids: Iterable[int],
) -> dict[int, ExternalSubscriptionSource]:
    """Lock sources in a deterministic order until the caller commits.

    A conditional no-op UPDATE is portable to the SQLite deployment while
    also taking a real row write lock on databases that support row-level
    locking.  This closes plan/source delete and plan/snapshot races without
    depending on SQLite foreign-key pragmas.
    """

    ordered_ids = sorted(set(source_ids))
    for source_id in ordered_ids:
        matched = (
            db.query(ExternalSubscriptionSource)
            .filter(ExternalSubscriptionSource.id == source_id)
            .update(
                {
                    ExternalSubscriptionSource.refresh_interval_minutes:
                        ExternalSubscriptionSource.refresh_interval_minutes,
                },
                synchronize_session=False,
            )
        )
        if matched != 1:
            db.rollback()
            raise ExternalSubscriptionConfigurationError("source_not_found")
    db.expire_all()
    sources = {
        source.id: source
        for source in db.query(ExternalSubscriptionSource)
        .filter(ExternalSubscriptionSource.id.in_(ordered_ids or [-1]))
        .with_for_update()
        .all()
    }
    if len(sources) != len(ordered_ids):
        db.rollback()
        raise ExternalSubscriptionConfigurationError("source_not_found")
    return sources


def lock_subscription_plans_for_update(
    db: Session,
    plan_ids: Iterable[int],
) -> None:
    """Serialize budget decisions shared by two or more source refreshes.

    Source rows alone are not a common lock when one plan references source A
    and source B.  A deterministic no-op UPDATE gives every refresh touching
    that plan the same serialization point on SQLite, MySQL and PostgreSQL.
    Budget reads below additionally use ``FOR UPDATE`` so MySQL's default
    REPEATABLE READ isolation observes commits made while waiting for this
    lock instead of continuing from an older consistent-read snapshot.
    """

    for plan_id in sorted(set(plan_ids)):
        matched = (
            db.query(SubscriptionPlan)
            .filter(SubscriptionPlan.id == plan_id)
            .update(
                {SubscriptionPlan.updated_at: SubscriptionPlan.updated_at},
                synchronize_session=False,
            )
        )
        if matched != 1:
            db.rollback()
            raise ExternalSubscriptionConfigurationError("plan_not_found")


def _raise_if_overlay_budget_exceeded(node_count: int, decrypted_bytes: int) -> None:
    if (
        node_count > MAX_OVERLAY_NODES
        or decrypted_bytes > MAX_OVERLAY_DECRYPTED_BYTES
    ):
        raise ExternalSubscriptionConfigurationError("overlay_limit_exceeded")


def validate_external_selection_budget(
    db: Session,
    specs: Iterable[ExternalSelectionSpec],
    *,
    override_source_id: Optional[int] = None,
    override_snapshot: Optional[ParsedExternalSnapshot] = None,
) -> ExternalProjectionBudget:
    """Validate the exact active overlay projected for one plan.

    During refresh, ``override_snapshot`` models the candidate source before
    any encrypted payload or node row is mutated. Selected-node grants follow
    stable external keys, so a disappeared node contributes zero and a node
    returning in the new snapshot contributes again.
    """

    normalized_specs = list(specs)
    node_count = 0
    decrypted_bytes = 0
    override_by_key = (
        {node.external_key: node for node in override_snapshot.nodes}
        if override_source_id is not None and override_snapshot is not None
        else {}
    )

    for spec in normalized_specs:
        if spec.mode not in {"all", "selected"}:
            raise ExternalSubscriptionConfigurationError("invalid_selection_mode")

        payloads: list[dict[str, Any]] = []
        if spec.source_id == override_source_id and override_snapshot is not None:
            if spec.mode == "all":
                payloads = [node.payload for node in override_snapshot.nodes]
            else:
                selected_ids = set(spec.node_ids)
                selected_keys = {
                    external_key
                    for _node_id, external_key in (
                        db.query(
                            ExternalSubscriptionNode.id,
                            ExternalSubscriptionNode.external_key,
                        )
                        .filter(
                            ExternalSubscriptionNode.source_id == spec.source_id,
                            ExternalSubscriptionNode.id.in_(selected_ids or {-1}),
                        )
                        .with_for_update()
                        .all()
                    )
                }
                payloads = [
                    node.payload
                    for key, node in override_by_key.items()
                    if key in selected_keys
                ]
        else:
            nodes_query = db.query(ExternalSubscriptionNode).filter(
                ExternalSubscriptionNode.source_id == spec.source_id,
                ExternalSubscriptionNode.is_active.is_(True),
            )
            if spec.mode == "selected":
                selected_ids = set(spec.node_ids)
                nodes_query = nodes_query.filter(
                    ExternalSubscriptionNode.id.in_(selected_ids or {-1})
                )
            nodes = nodes_query.order_by(
                ExternalSubscriptionNode.position.asc(),
                ExternalSubscriptionNode.id.asc(),
            ).with_for_update().all()
            payloads = [
                decrypt_proxy_payload(node.payload_ciphertext)
                for node in nodes
            ]

        for payload in payloads:
            node_count += 1
            decrypted_bytes += len(_canonical_proxy_payload_bytes(payload))
            _raise_if_overlay_budget_exceeded(node_count, decrypted_bytes)

    return ExternalProjectionBudget(
        node_count=node_count,
        decrypted_bytes=decrypted_bytes,
    )


def _validate_snapshot_plan_budgets(
    db: Session,
    source_id: int,
    snapshot: ParsedExternalSnapshot,
) -> None:
    plan_ids = [
        plan_id
        for (plan_id,) in (
            db.query(SubscriptionPlanExternalSelection.plan_id)
            .filter(SubscriptionPlanExternalSelection.source_id == source_id)
            .order_by(SubscriptionPlanExternalSelection.plan_id.asc())
            .with_for_update()
            .all()
        )
    ]
    lock_subscription_plans_for_update(db, plan_ids)
    for plan_id in plan_ids:
        selections = (
            db.query(SubscriptionPlanExternalSelection)
            .filter(SubscriptionPlanExternalSelection.plan_id == plan_id)
            .order_by(SubscriptionPlanExternalSelection.source_id.asc())
            .with_for_update()
            .all()
        )
        selected_node_ids: dict[int, list[int]] = {
            selection.id: [] for selection in selections
        }
        if selected_node_ids:
            for selection_id, node_id in (
                db.query(
                    plan_external_selected_nodes.c.selection_id,
                    plan_external_selected_nodes.c.node_id,
                )
                .filter(
                    plan_external_selected_nodes.c.selection_id.in_(
                        selected_node_ids
                    )
                )
                .order_by(
                    plan_external_selected_nodes.c.selection_id.asc(),
                    plan_external_selected_nodes.c.node_id.asc(),
                )
                .with_for_update()
                .all()
            ):
                selected_node_ids[selection_id].append(node_id)
        specs = [
            ExternalSelectionSpec(
                source_id=selection.source_id,
                mode=selection.mode,
                node_ids=tuple(selected_node_ids[selection.id]),
            )
            for selection in selections
        ]
        validate_external_selection_budget(
            db,
            specs,
            override_source_id=source_id,
            override_snapshot=snapshot,
        )


def _normalize_yaml_value(
    value: Any,
    *,
    depth: int = 0,
    ancestors: Optional[set[int]] = None,
    budget: Optional[list[int]] = None,
) -> Any:
    if depth > MAX_YAML_DEPTH:
        raise ExternalSubscriptionParseError("yaml_too_deep")
    ancestors = ancestors if ancestors is not None else set()
    budget = budget if budget is not None else [MAX_YAML_ITEMS]
    budget[0] -= 1
    if budget[0] < 0:
        raise ExternalSubscriptionParseError("yaml_too_complex")

    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_YAML_STRING_BYTES:
            raise ExternalSubscriptionParseError("yaml_string_too_large")
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExternalSubscriptionParseError("invalid_yaml_value")
        return value
    if isinstance(value, (list, dict)):
        object_id = id(value)
        if object_id in ancestors:
            raise ExternalSubscriptionParseError("yaml_cycle_not_allowed")
        ancestors.add(object_id)
        try:
            if isinstance(value, list):
                return [
                    _normalize_yaml_value(
                        item,
                        depth=depth + 1,
                        ancestors=ancestors,
                        budget=budget,
                    )
                    for item in value
                ]
            result = {}
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 256:
                    raise ExternalSubscriptionParseError("invalid_yaml_key")
                result[key] = _normalize_yaml_value(
                    item,
                    depth=depth + 1,
                    ancestors=ancestors,
                    budget=budget,
                )
            return result
        finally:
            ancestors.remove(object_id)
    raise ExternalSubscriptionParseError("invalid_yaml_value")


def _node_identity(
    name: str,
    proxy_type: str,
    server: str,
    port: int,
    occurrence: int,
) -> str:
    material = json.dumps(
        [name, proxy_type, server, port, occurrence],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_clash_subscription(content: bytes) -> ParsedExternalSnapshot:
    if len(content) > MAX_SOURCE_BYTES:
        raise ExternalSubscriptionParseError("source_too_large")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError:
        raise ExternalSubscriptionParseError("invalid_encoding") from None

    try:
        depth = 0
        token_count = 0
        collection_starts = (
            BlockMappingStartToken,
            BlockSequenceStartToken,
            FlowMappingStartToken,
            FlowSequenceStartToken,
        )
        collection_ends = (BlockEndToken, FlowMappingEndToken, FlowSequenceEndToken)
        for token in yaml.scan(text, Loader=_UniqueKeySafeLoader):
            token_count += 1
            if token_count > MAX_YAML_TOKENS:
                raise ExternalSubscriptionParseError("yaml_too_complex")
            if isinstance(token, (AliasToken, AnchorToken)):
                raise ExternalSubscriptionParseError("yaml_aliases_not_allowed")
            if isinstance(token, collection_starts):
                depth += 1
                if depth > MAX_YAML_DEPTH:
                    raise ExternalSubscriptionParseError("yaml_too_deep")
            elif isinstance(token, collection_ends):
                depth = max(0, depth - 1)
        document = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except ExternalSubscriptionParseError:
        raise
    except RecursionError:
        raise ExternalSubscriptionParseError("yaml_too_deep") from None
    except yaml.YAMLError:
        raise ExternalSubscriptionParseError("invalid_yaml") from None

    if not isinstance(document, dict):
        raise ExternalSubscriptionParseError("invalid_clash_document")
    raw_nodes = document.get("proxies")
    if not isinstance(raw_nodes, list):
        raise ExternalSubscriptionParseError("missing_proxies")
    if len(raw_nodes) > MAX_SOURCE_NODES:
        raise ExternalSubscriptionParseError("too_many_nodes")

    parsed = []
    skipped = 0
    endpoint_occurrences: dict[tuple[str, str, str, int], int] = {}
    for position, raw_node in enumerate(raw_nodes):
        try:
            node = _normalize_yaml_value(raw_node)
            if not isinstance(node, dict):
                raise ExternalSubscriptionParseError("invalid_node")
            if any(key in node for key in _UPSTREAM_REFERENCE_KEYS):
                skipped += 1
                continue
            name_value = node.get("name")
            proxy_type = node.get("type")
            server = node.get("server")
            port = node.get("port")
            if not isinstance(name_value, str) or not name_value.strip():
                raise ExternalSubscriptionParseError("invalid_node")
            name = unicodedata.normalize("NFKC", name_value.strip())
            if len(name) > 256 or any(
                unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}
                for char in name
            ):
                raise ExternalSubscriptionParseError("invalid_node")
            if not isinstance(proxy_type, str):
                raise ExternalSubscriptionParseError("invalid_node")
            proxy_type = proxy_type.strip().lower()
            if (
                not EXTERNAL_PROXY_TYPE_RE.fullmatch(proxy_type)
                or proxy_type not in MIHOMO_EXTERNAL_PROXY_TYPES
            ):
                raise ExternalSubscriptionParseError("invalid_node")
            if not isinstance(server, str) or not server.strip() or len(server) > 512:
                raise ExternalSubscriptionParseError("invalid_node")
            if isinstance(port, str) and port.isascii() and port.isdigit():
                port = int(port)
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ExternalSubscriptionParseError("invalid_node")
            node["name"] = name
            node["type"] = proxy_type
            node["server"] = server.strip()
            node["port"] = port
            try:
                canonical = json.dumps(
                    node,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError):
                raise ExternalSubscriptionParseError("invalid_node") from None
            if len(canonical) > MAX_NODE_JSON_BYTES:
                raise ExternalSubscriptionParseError("node_too_large")
            identity = (name, proxy_type, node["server"], port)
            occurrence = endpoint_occurrences.get(identity, 0)
            endpoint_occurrences[identity] = occurrence + 1
            parsed.append(
                ParsedExternalNode(
                    external_key=_node_identity(
                        name,
                        proxy_type,
                        node["server"],
                        port,
                        occurrence,
                    ),
                    name=name,
                    proxy_type=node["type"],
                    payload=node,
                    position=position,
                )
            )
        except (ExternalSubscriptionParseError, RecursionError):
            skipped += 1

    if not parsed:
        raise ExternalSubscriptionParseError("no_usable_nodes")
    return ParsedExternalSnapshot(tuple(parsed), skipped)


def _clean_header(value: Optional[str], max_length: int) -> Optional[str]:
    if not value or any(ord(char) < 32 for char in value):
        return None
    return value[:max_length]


def _validate_public_https_url(value: str) -> ValidatedExternalURL:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 4096
        or not value.isascii()
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ExternalSubscriptionFetchError("invalid_url")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ExternalSubscriptionFetchError("invalid_url") from None
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port not in (None, 443)
    ):
        raise ExternalSubscriptionFetchError("invalid_url")

    hostname = parts.hostname.rstrip(".")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise ExternalSubscriptionFetchError("invalid_url") from None
    if not hostname or hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        raise ExternalSubscriptionFetchError("non_public_destination")
    try:
        resolved = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError:
        raise ExternalSubscriptionFetchError("dns_error") from None
    if not resolved:
        raise ExternalSubscriptionFetchError("dns_error")
    try:
        addresses = [ipaddress.ip_address(address) for address in resolved]
    except ValueError:
        raise ExternalSubscriptionFetchError("dns_error") from None
    if any(not address.is_global for address in addresses):
        raise ExternalSubscriptionFetchError("non_public_destination")

    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    path = parts.path or "/"
    request_target = path + (f"?{parts.query}" if parts.query else "")
    return ValidatedExternalURL(
        url=urlunsplit(("https", netloc, path, parts.query, "")),
        hostname=hostname,
        host_header=netloc,
        request_target=request_target,
        addresses=tuple(sorted(str(address) for address in addresses)),
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that never resolves the validated hostname again."""

    def __init__(
        self,
        hostname: str,
        pinned_address: str,
        *,
        timeout: float,
    ) -> None:
        super().__init__(
            hostname,
            port=443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_address = pinned_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(
            self.sock,
            server_hostname=self.host,
        )


def _open_pinned_response(
    target: ValidatedExternalURL,
    *,
    headers: dict[str, str],
    deadline: float,
) -> tuple[_PinnedHTTPSConnection, http.client.HTTPResponse]:
    saw_tls_error = False
    saw_timeout = False
    for address in target.addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExternalSubscriptionFetchError("timeout")
        connection = _PinnedHTTPSConnection(
            target.hostname,
            address,
            timeout=max(0.1, min(5.0, remaining)),
        )
        try:
            connection.request(
                "GET",
                target.request_target,
                headers={**headers, "Host": target.host_header},
            )
            return connection, connection.getresponse()
        except (socket.timeout, TimeoutError):
            saw_timeout = True
            connection.close()
        except ssl.SSLError:
            saw_tls_error = True
            connection.close()
        except (OSError, http.client.HTTPException):
            connection.close()
    if time.monotonic() >= deadline or saw_timeout:
        raise ExternalSubscriptionFetchError("timeout")
    if saw_tls_error:
        raise ExternalSubscriptionFetchError("tls_error")
    raise ExternalSubscriptionFetchError("network_error")


def fetch_clash_subscription(
    url: str,
    *,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
) -> FetchedExternalPayload:
    current = _validate_public_https_url(url)
    headers = {
        "Accept": "*/*",
        "User-Agent": MIHOMO_COMPATIBLE_USER_AGENT,
        "Accept-Encoding": "identity",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    deadline = time.monotonic() + FETCH_DEADLINE_SECONDS
    redirects = 0
    while True:
        connection, response = _open_pinned_response(
            current,
            headers=headers,
            deadline=deadline,
        )
        try:
            if response.status in _REDIRECT_STATUSES:
                if redirects >= MAX_REDIRECTS:
                    raise ExternalSubscriptionFetchError("too_many_redirects")
                location = response.headers.get("Location")
                if not location:
                    raise ExternalSubscriptionFetchError("invalid_redirect")
                current = _validate_public_https_url(urljoin(current.url, location))
                redirects += 1
                continue
            if response.status == 304:
                return FetchedExternalPayload(
                    content=None,
                    etag=_clean_header(response.headers.get("ETag"), 512) or etag,
                    last_modified=(
                        _clean_header(response.headers.get("Last-Modified"), 128)
                        or last_modified
                    ),
                    not_modified=True,
                )
            if response.status in (401, 403, 404, 410):
                # Keep the projection secret-free while preserving the actual
                # upstream status. A 403 can be a UA/WAF/IP policy failure,
                # while a 404/410 may be an expired or intentionally hidden
                # authorization resource.
                raise ExternalSubscriptionFetchError(
                    f"upstream_http_{response.status}"
                )
            if not 200 <= response.status < 300:
                raise ExternalSubscriptionFetchError("http_error")

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_SOURCE_BYTES:
                        raise ExternalSubscriptionFetchError("source_too_large")
                except ValueError:
                    pass
            chunks: list[bytes] = []
            total = 0
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ExternalSubscriptionFetchError("timeout")
                    if connection.sock is not None:
                        connection.sock.settimeout(max(0.1, remaining))
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ExternalSubscriptionFetchError("source_too_large")
                    chunks.append(chunk)
            except (socket.timeout, TimeoutError):
                raise ExternalSubscriptionFetchError("timeout") from None
            except (OSError, http.client.HTTPException):
                raise ExternalSubscriptionFetchError("network_error") from None
            return FetchedExternalPayload(
                content=b"".join(chunks),
                etag=_clean_header(response.headers.get("ETag"), 512),
                last_modified=_clean_header(response.headers.get("Last-Modified"), 128),
            )
        finally:
            response.close()
            connection.close()


def _next_refresh(source: ExternalSubscriptionSource, now: datetime) -> Optional[datetime]:
    if not source.enabled or not source.url_ciphertext:
        return None
    return now + timedelta(minutes=max(MIN_REFRESH_INTERVAL_MINUTES, source.refresh_interval_minutes))


def create_source(
    db: Session,
    *,
    name: str,
    group_name: str,
    created_by: str,
    enabled: bool = True,
    refresh_interval_minutes: int = DEFAULT_REFRESH_INTERVAL_MINUTES,
    url: Optional[str] = None,
) -> ExternalSubscriptionSource:
    # Fail at setup time instead of accepting a source that can never persist
    # its write-only credential or node payloads.
    _fernet()
    now = utc_now()
    ciphertext = encrypt_url(_validate_public_https_url(url).url) if url else None
    source = ExternalSubscriptionSource(
        name=name.strip(),
        group_name=group_name.strip(),
        created_by=created_by,
        enabled=enabled,
        refresh_interval_minutes=refresh_interval_minutes,
        url_ciphertext=ciphertext,
        url_revision=1 if ciphertext else 0,
        status="empty" if enabled else "disabled",
        next_refresh_at=now if enabled and ciphertext else None,
        created_at=now,
        updated_at=now,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def replace_source_url(
    db: Session,
    source: ExternalSubscriptionSource,
    url: Optional[str],
) -> ExternalSubscriptionSource:
    if url:
        _fernet()
    source.url_ciphertext = (
        encrypt_url(_validate_public_https_url(url).url) if url else None
    )
    source.url_revision += 1
    # Credential replacement supersedes any in-flight request. The old worker
    # checks both revision and lease token before it can publish a snapshot.
    source.refresh_lease_until = None
    source.refresh_lease_token = None
    source.etag = None
    source.last_modified = None
    source.last_error_code = None
    source.next_refresh_at = utc_now() if source.enabled and url else None
    if not source.enabled:
        source.status = "disabled"
    elif source.node_count:
        source.status = "ready"
    else:
        source.status = "empty"
    source.updated_at = utc_now()
    db.commit()
    db.refresh(source)
    return source


def _claim_refresh_lease(
    db: Session,
    source_id: int,
    *,
    now: datetime,
    require_enabled: bool,
) -> tuple[ExternalSubscriptionSource, str]:
    token = secrets.token_urlsafe(24)
    query = db.query(ExternalSubscriptionSource).filter(
        ExternalSubscriptionSource.id == source_id,
        or_(
            ExternalSubscriptionSource.refresh_lease_until.is_(None),
            ExternalSubscriptionSource.refresh_lease_until <= now,
        ),
    )
    # Every remote refresh needs a credential.  The enabled flag controls only
    # the scheduler; an explicit administrator refresh may bypass it.
    query = query.filter(ExternalSubscriptionSource.url_ciphertext.is_not(None))
    if require_enabled:
        query = query.filter(ExternalSubscriptionSource.enabled.is_(True))
    claimed = query.update(
        {
            ExternalSubscriptionSource.refresh_lease_until: now
            + timedelta(seconds=REFRESH_LEASE_SECONDS),
            ExternalSubscriptionSource.refresh_lease_token: token,
        },
        synchronize_session=False,
    )
    db.commit()
    db.expire_all()
    source = db.get(ExternalSubscriptionSource, source_id)
    if source is None:
        raise ExternalSubscriptionConfigurationError("source_not_found")
    if claimed:
        return source, token
    if require_enabled and not source.enabled:
        raise ExternalSubscriptionConfigurationError("source_disabled")
    if not source.url_ciphertext:
        raise ExternalSubscriptionConfigurationError("credential_not_configured")
    raise ExternalSubscriptionConfigurationError("refresh_in_progress")


def _release_refresh_lease(
    db: Session,
    source_id: int,
    token: str,
) -> None:
    try:
        db.rollback()
        db.query(ExternalSubscriptionSource).filter(
            ExternalSubscriptionSource.id == source_id,
            ExternalSubscriptionSource.refresh_lease_token == token,
        ).update(
            {
                ExternalSubscriptionSource.refresh_lease_until: None,
                ExternalSubscriptionSource.refresh_lease_token: None,
            },
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        # Do not mask the refresh result. A failed release is bounded by the
        # short lease expiration and can be claimed safely afterwards.
        db.rollback()


def _claim_snapshot_lease(
    db: Session,
    source_id: int,
    *,
    now: datetime,
) -> tuple[ExternalSubscriptionSource, str]:
    """Supersede an in-flight remote generation with a manual snapshot."""

    token = secrets.token_urlsafe(24)
    updated = db.query(ExternalSubscriptionSource).filter(
        ExternalSubscriptionSource.id == source_id,
    ).update(
        {
            ExternalSubscriptionSource.url_revision:
                ExternalSubscriptionSource.url_revision + 1,
            ExternalSubscriptionSource.etag: None,
            ExternalSubscriptionSource.last_modified: None,
            ExternalSubscriptionSource.refresh_lease_until: now
            + timedelta(seconds=REFRESH_LEASE_SECONDS),
            ExternalSubscriptionSource.refresh_lease_token: token,
        },
        synchronize_session=False,
    )
    db.commit()
    if not updated:
        raise ExternalSubscriptionConfigurationError("source_not_found")
    db.expire_all()
    source = db.get(ExternalSubscriptionSource, source_id)
    if source is None:
        raise ExternalSubscriptionConfigurationError("source_not_found")
    return source, token


def update_source(
    db: Session,
    source: ExternalSubscriptionSource,
    *,
    name: Optional[str] = None,
    enabled: Optional[bool] = None,
    refresh_interval_minutes: Optional[int] = None,
) -> ExternalSubscriptionSource:
    now = utc_now()
    was_enabled = source.enabled
    if name is not None:
        source.name = name.strip()
    if refresh_interval_minutes is not None:
        source.refresh_interval_minutes = refresh_interval_minutes
    if enabled is not None:
        source.enabled = enabled
    if not source.enabled:
        # Disabling scheduled refreshes also supersedes a generation that was
        # claimed while the source was enabled. This prevents a stale worker
        # from restoring ready/next-refresh metadata after the switch is off.
        if was_enabled:
            source.url_revision += 1
            source.refresh_lease_until = None
            source.refresh_lease_token = None
        source.status = "disabled"
        source.next_refresh_at = None
    elif not was_enabled:
        source.status = "ready" if source.node_count else "empty"
        source.next_refresh_at = now if source.url_ciphertext else None
    elif refresh_interval_minutes is not None and source.status != "auth_required":
        source.next_refresh_at = (
            now + timedelta(minutes=source.refresh_interval_minutes)
            if source.url_ciphertext
            else None
        )
    source.updated_at = now
    db.commit()
    db.refresh(source)
    return source


def _apply_snapshot(
    db: Session,
    source: ExternalSubscriptionSource,
    snapshot: ParsedExternalSnapshot,
    *,
    now: datetime,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
    remote: bool,
    lease_token: str,
) -> ExternalSubscriptionSource:
    # This must be the first write lock in snapshot publication. Plan edits use
    # the same global -> source ordering, preventing A/B refresh deadlocks.
    lock_external_budget_for_update(db)
    # Acquire a database write lock only if this generation still owns the
    # lease. Holding it through the node mutations closes the manual/manual
    # and manual/remote TOCTOU window across workers.
    owns_generation = db.query(ExternalSubscriptionSource).filter(
        ExternalSubscriptionSource.id == source.id,
        ExternalSubscriptionSource.refresh_lease_token == lease_token,
    ).update(
        {
            ExternalSubscriptionSource.refresh_lease_until:
                ExternalSubscriptionSource.refresh_lease_until,
        },
        synchronize_session=False,
    )
    if owns_generation != 1:
        db.rollback()
        raise ExternalSubscriptionConfigurationError("refresh_superseded")
    db.expire(
        source,
        ["refresh_lease_token", "url_revision"],
    )
    if source.refresh_lease_token != lease_token:
        db.rollback()
        raise ExternalSubscriptionConfigurationError("refresh_superseded")
    # Validate every referencing plan against the candidate generation before
    # touching last-known-good node rows.  Any failure leaves the old snapshot
    # intact and is surfaced as a stable refresh error.
    _validate_snapshot_plan_budgets(db, source.id, snapshot)
    encrypted = [
        (node, encrypt_proxy_payload(node.payload))
        for node in snapshot.nodes
    ]
    existing = {node.external_key: node for node in source.nodes}
    selected_node_ids = {
        node_id
        for (node_id,) in db.query(plan_external_selected_nodes.c.node_id)
        .join(
            ExternalSubscriptionNode,
            ExternalSubscriptionNode.id == plan_external_selected_nodes.c.node_id,
        )
        .filter(
            ExternalSubscriptionNode.source_id == source.id,
        )
        .all()
    }
    seen = set()
    for parsed, ciphertext in encrypted:
        seen.add(parsed.external_key)
        node = existing.get(parsed.external_key)
        if node is None:
            node = ExternalSubscriptionNode(
                source=source,
                external_key=parsed.external_key,
                first_seen_at=now,
            )
            db.add(node)
        node.name = parsed.name
        node.proxy_type = parsed.proxy_type
        node.payload_ciphertext = ciphertext
        node.position = parsed.position
        node.is_active = True
        node.last_seen_at = now
        node.updated_at = now
    for key, node in existing.items():
        if key not in seen:
            if node.id in selected_node_ids:
                node.is_active = False
                node.updated_at = now
            else:
                db.delete(node)

    source.node_count = len(snapshot.nodes)
    source.skipped_node_count = snapshot.skipped_node_count
    source.status = "ready" if source.enabled else "disabled"
    source.last_attempt_at = now
    source.last_success_at = now
    source.last_error_code = None
    if remote:
        source.etag = etag
        source.last_modified = last_modified
    else:
        # A manual snapshot supersedes the cached HTTP representation.  The
        # next remote refresh must fetch a full body rather than accept 304.
        source.etag = None
        source.last_modified = None
    source.next_refresh_at = _next_refresh(source, now)
    source.refresh_lease_until = None
    source.refresh_lease_token = None
    source.updated_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(source)
    return source


def import_snapshot(
    db: Session,
    source: ExternalSubscriptionSource,
    content: bytes,
    *,
    now: Optional[datetime] = None,
) -> ExternalSubscriptionSource:
    snapshot = parse_clash_subscription(content)
    attempt_at = utc_now(now)
    claimed, lease_token = _claim_snapshot_lease(
        db,
        source.id,
        now=attempt_at,
    )
    try:
        return _apply_snapshot(
            db,
            claimed,
            snapshot,
            now=attempt_at,
            remote=False,
            lease_token=lease_token,
        )
    except ExternalSubscriptionError:
        raise
    except Exception:
        db.rollback()
        raise ExternalSubscriptionConfigurationError("internal_error") from None
    finally:
        _release_refresh_lease(db, source.id, lease_token)


def _record_refresh_failure(
    db: Session,
    source_id: int,
    code: str,
    *,
    now: datetime,
    url_revision: int,
    lease_token: str,
) -> ExternalSubscriptionSource:
    db.expire_all()
    source = db.get(ExternalSubscriptionSource, source_id)
    if source is None:
        raise ExternalSubscriptionConfigurationError("source_not_found")
    if (
        source.url_revision != url_revision
        or source.refresh_lease_token != lease_token
    ):
        return source
    source.last_attempt_at = now
    source.last_error_code = code
    auth_required = code in _AUTH_REQUIRED_ERROR_CODES or code == "auth_required"
    source.status = "auth_required" if auth_required else "error"
    if not source.enabled:
        source.status = "disabled"
    source.next_refresh_at = (
        None if auth_required else _next_refresh(source, now)
    )
    source.refresh_lease_until = None
    source.refresh_lease_token = None
    source.updated_at = now
    db.commit()
    db.refresh(source)
    return source


def refresh_source(
    db: Session,
    source_id: int,
    *,
    now: Optional[datetime] = None,
    scheduled: bool = False,
) -> ExternalSubscriptionSource:
    source = db.get(ExternalSubscriptionSource, source_id)
    if source is None:
        raise ExternalSubscriptionConfigurationError("source_not_found")
    # A disabled source has automatic refreshes turned off, but administrators
    # can still refresh it explicitly and its last-known-good nodes remain in
    # user subscriptions.
    if scheduled and not source.enabled:
        return source
    if not source.url_ciphertext:
        raise ExternalSubscriptionConfigurationError("credential_not_configured")

    attempt_at = utc_now(now)
    source, lease_token = _claim_refresh_lease(
        db,
        source_id,
        now=attempt_at,
        require_enabled=scheduled,
    )
    url_revision = source.url_revision
    ciphertext = source.url_ciphertext
    etag = source.etag
    last_modified = source.last_modified
    try:
        fetched = fetch_clash_subscription(
            decrypt_url(ciphertext),
            etag=etag,
            last_modified=last_modified,
        )
        snapshot = (
            parse_clash_subscription(fetched.content or b"")
            if not fetched.not_modified
            else None
        )

        db.expire_all()
        current = db.get(ExternalSubscriptionSource, source_id)
        if current is None:
            raise ExternalSubscriptionConfigurationError("source_not_found")
        if (
            current.url_revision != url_revision
            or current.refresh_lease_token != lease_token
        ):
            return current
        if fetched.not_modified:
            current.last_attempt_at = attempt_at
            current.last_success_at = attempt_at
            current.last_error_code = None
            current.status = "ready" if current.enabled else "disabled"
            current.etag = fetched.etag
            current.last_modified = fetched.last_modified
            current.next_refresh_at = _next_refresh(current, attempt_at)
            current.refresh_lease_until = None
            current.refresh_lease_token = None
            current.updated_at = attempt_at
            db.commit()
            db.refresh(current)
            return current
        return _apply_snapshot(
            db,
            current,
            snapshot,
            now=attempt_at,
            etag=fetched.etag,
            last_modified=fetched.last_modified,
            remote=True,
            lease_token=lease_token,
        )
    except ExternalSubscriptionError as exc:
        try:
            _record_refresh_failure(
                db,
                source_id,
                exc.code,
                now=attempt_at,
                url_revision=url_revision,
                lease_token=lease_token,
            )
        except Exception:
            db.rollback()
        raise
    except Exception:
        try:
            _record_refresh_failure(
                db,
                source_id,
                "internal_error",
                now=attempt_at,
                url_revision=url_revision,
                lease_token=lease_token,
            )
        except Exception:
            db.rollback()
        raise ExternalSubscriptionConfigurationError("internal_error") from None
    finally:
        _release_refresh_lease(db, source_id, lease_token)


def due_source_ids(
    db: Session,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> list[int]:
    current = utc_now(now)
    return [
        source_id
        for (source_id,) in (
            db.query(ExternalSubscriptionSource.id)
            .filter(
                ExternalSubscriptionSource.enabled.is_(True),
                ExternalSubscriptionSource.url_ciphertext.is_not(None),
                ExternalSubscriptionSource.next_refresh_at.is_not(None),
                ExternalSubscriptionSource.next_refresh_at <= current,
                or_(
                    ExternalSubscriptionSource.refresh_lease_until.is_(None),
                    ExternalSubscriptionSource.refresh_lease_until <= current,
                ),
            )
            .order_by(ExternalSubscriptionSource.next_refresh_at.asc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
    ]


def load_external_overlays_for_user(
    db: Session,
    user_id: int,
) -> list[ExternalOverlaySource]:
    selections = (
        db.query(SubscriptionPlanExternalSelection)
        .join(
            PortalSubscription,
            PortalSubscription.plan_id == SubscriptionPlanExternalSelection.plan_id,
        )
        .join(PortalAccount, PortalAccount.id == PortalSubscription.account_id)
        .options(
            joinedload(SubscriptionPlanExternalSelection.source),
        )
        .filter(
            PortalAccount.user_id == user_id,
            PortalSubscription.disabled_at.is_(None),
        )
        .order_by(SubscriptionPlanExternalSelection.id.asc())
        .all()
    )

    all_source_ids = {
        selection.source_id
        for selection in selections
        if selection.mode == "all" and selection.source
    }
    active_by_source: dict[int, list[ExternalSubscriptionNode]] = {
        source_id: [] for source_id in all_source_ids
    }
    all_nodes: list[ExternalSubscriptionNode] = []
    if all_source_ids:
        all_nodes = (
            db.query(ExternalSubscriptionNode)
            .filter(
                ExternalSubscriptionNode.source_id.in_(all_source_ids),
                ExternalSubscriptionNode.is_active.is_(True),
            )
            .order_by(
                ExternalSubscriptionNode.source_id.asc(),
                ExternalSubscriptionNode.position.asc(),
                ExternalSubscriptionNode.id.asc(),
            )
            .limit(MAX_OVERLAY_NODES + 1)
            .all()
        )
        if len(all_nodes) > MAX_OVERLAY_NODES:
            raise ExternalSubscriptionConfigurationError("overlay_limit_exceeded")
        for node in all_nodes:
            active_by_source[node.source_id].append(node)

    selected_selections = {
        selection.id: selection
        for selection in selections
        if selection.mode == "selected" and selection.source
    }
    selected_by_selection: dict[int, list[ExternalSubscriptionNode]] = {
        selection_id: [] for selection_id in selected_selections
    }
    selected_rows = []
    if selected_selections:
        selected_rows = (
            db.query(
                plan_external_selected_nodes.c.selection_id,
                ExternalSubscriptionNode,
            )
            .join(
                ExternalSubscriptionNode,
                ExternalSubscriptionNode.id
                == plan_external_selected_nodes.c.node_id,
            )
            .filter(
                plan_external_selected_nodes.c.selection_id.in_(
                    selected_selections
                ),
                ExternalSubscriptionNode.is_active.is_(True),
            )
            .order_by(
                plan_external_selected_nodes.c.selection_id.asc(),
                ExternalSubscriptionNode.position.asc(),
                ExternalSubscriptionNode.id.asc(),
            )
            .limit(MAX_OVERLAY_NODES + 1)
            .all()
        )
        if len(selected_rows) > MAX_OVERLAY_NODES:
            raise ExternalSubscriptionConfigurationError("overlay_limit_exceeded")
        for selection_id, node in selected_rows:
            selection = selected_selections[selection_id]
            if node.source_id == selection.source_id:
                selected_by_selection[selection_id].append(node)

    candidate_count = len(all_nodes) + sum(
        len(nodes) for nodes in selected_by_selection.values()
    )
    if candidate_count > MAX_OVERLAY_NODES:
        raise ExternalSubscriptionConfigurationError("overlay_limit_exceeded")

    overlays = []
    decrypted_bytes = 0
    for selection in selections:
        source = selection.source
        if not source:
            continue
        candidates: Iterable[ExternalSubscriptionNode]
        if selection.mode == "all":
            candidates = active_by_source.get(source.id, ())
        else:
            candidates = selected_by_selection.get(selection.id, ())
        payloads = []
        for node in sorted(candidates, key=lambda item: (item.position, item.id)):
            if not node.is_active or node.source_id != source.id:
                continue
            try:
                payload = decrypt_proxy_payload(node.payload_ciphertext)
            except ExternalSubscriptionConfigurationError as exc:
                logger.error(
                    "External subscription node decrypt failed: source_id=%s node_id=%s code=%s",
                    source.id,
                    node.id,
                    exc.code,
                )
                raise
            decrypted_bytes += len(_canonical_proxy_payload_bytes(payload))
            _raise_if_overlay_budget_exceeded(candidate_count, decrypted_bytes)
            # Renderer owns collision-safe display naming.  Keep the original
            # upstream name here to avoid applying the source prefix twice.
            payload["name"] = node.name
            payloads.append(payload)
        if payloads:
            overlays.append(
                ExternalOverlaySource(
                    source_id=source.id,
                    group_name=source.group_name,
                    nodes=tuple(payloads),
                )
            )
    return overlays
