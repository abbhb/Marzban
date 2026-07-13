"""Core service for short-lived MGMA subscription URLs.

The service intentionally separates the clear-text bearer token from database
state: callers receive the clear text once, while only an HMAC-SHA256 digest is
stored. Public routes should map every :class:`MgmaTokenRejected` to the same
404 response and must never include the token in logs or response headers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, collapse_addresses, ip_address, ip_network
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Union
from urllib.parse import quote

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db.models import MgmaSettings, User
from app.models.mgma import (
    MgmaAccessMode,
    MgmaSettingsResponse,
    MgmaSettingsUpdate,
    MgmaSourceMode,
    MgmaTokenIssue,
)
from app.models.user import UserStatus
from config import XRAY_SUBSCRIPTION_PATH, XRAY_SUBSCRIPTION_URL_PREFIX


MGMA_TOKEN_PEPPER_ENV = "MGMA_TOKEN_PEPPER"
MGMA_TOKEN_BYTES = 32
MGMA_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
MGMA_SETTINGS_ID = 1

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CN_CIDR_PATH = DATA_DIR / "cn.cidr"
CN_CIDR_METADATA_PATH = DATA_DIR / "cn-cidr-metadata.json"

IPAddress = Union[IPv4Address, IPv6Address]
IPNetwork = Union[IPv4Network, IPv6Network]


class MgmaError(Exception):
    """Base class for MGMA service failures."""


class MgmaConfigurationError(MgmaError):
    """Raised for an unsafe or unusable MGMA configuration."""


class MgmaUserIneligible(MgmaError):
    """Raised when a disabled/expired/limited user cannot receive a token."""


class MgmaTokenRejected(MgmaError):
    """Opaque public-token validation failure.

    Do not expose failure subtypes to unauthenticated callers. A malformed,
    expired, consumed, source-denied, and unknown token should look identical.
    """


@dataclass(frozen=True)
class _AddressFamilyIndex:
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    def contains(self, value: int) -> bool:
        position = bisect_right(self.starts, value) - 1
        return position >= 0 and value <= self.ends[position]


@dataclass(frozen=True)
class CidrIndex:
    """Compact, binary-searchable IPv4 and IPv6 CIDR index."""

    ipv4: _AddressFamilyIndex
    ipv6: _AddressFamilyIndex
    count: int

    def contains(self, address: IPAddress) -> bool:
        family = self.ipv4 if address.version == 4 else self.ipv6
        return family.contains(int(address))


def _family_index(networks: Iterable[IPNetwork]) -> _AddressFamilyIndex:
    intervals = sorted(
        (int(network.network_address), int(network.broadcast_address))
        for network in networks
    )
    return _AddressFamilyIndex(
        starts=tuple(item[0] for item in intervals),
        ends=tuple(item[1] for item in intervals),
    )


def _build_cidr_index(networks: Iterable[IPNetwork]) -> CidrIndex:
    ipv4 = []
    ipv6 = []
    for network in networks:
        (ipv4 if network.version == 4 else ipv6).append(network)

    # Collapse again at load time so hand-edited custom snapshots cannot create
    # overlapping intervals that would invalidate the binary-search invariant.
    collapsed_v4 = list(collapse_addresses(ipv4))
    collapsed_v6 = list(collapse_addresses(ipv6))
    return CidrIndex(
        ipv4=_family_index(collapsed_v4),
        ipv6=_family_index(collapsed_v6),
        count=len(collapsed_v4) + len(collapsed_v6),
    )


def _parse_cidrs(lines: Iterable[str]) -> CidrIndex:
    networks = []
    for line_number, line in enumerate(lines, start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError as exc:
            raise MgmaConfigurationError(
                f"invalid CIDR snapshot entry at line {line_number}"
            ) from exc
    return _build_cidr_index(networks)


@lru_cache(maxsize=4)
def load_cidr_index(path: str) -> CidrIndex:
    """Load and cache a newline-delimited IPv4/IPv6 CIDR file."""

    try:
        with open(path, "r", encoding="utf-8") as cidr_file:
            return _parse_cidrs(cidr_file)
    except OSError as exc:
        raise MgmaConfigurationError("CIDR snapshot is unavailable") from exc


def load_china_cidr_index() -> CidrIndex:
    return load_cidr_index(str(CN_CIDR_PATH))


@lru_cache(maxsize=1)
def load_china_cidr_metadata() -> Mapping[str, object]:
    try:
        with open(CN_CIDR_METADATA_PATH, "r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    except (OSError, ValueError, TypeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def clear_cidr_caches() -> None:
    """Clear file caches after replacing the offline snapshot (or in tests)."""

    load_cidr_index.cache_clear()
    load_china_cidr_metadata.cache_clear()
    _custom_cidr_index.cache_clear()


def get_token_pepper() -> Optional[str]:
    """Read the pepper at call time so rotation takes effect without import leaks."""

    value = os.getenv(MGMA_TOKEN_PEPPER_ENV)
    return value if value else None


def pepper_is_configured() -> bool:
    pepper = get_token_pepper()
    return bool(pepper and len(pepper.encode("utf-8")) >= 32)


def require_token_pepper() -> str:
    pepper = get_token_pepper()
    if not pepper or len(pepper.encode("utf-8")) < 32:
        raise MgmaConfigurationError(
            f"{MGMA_TOKEN_PEPPER_ENV} must contain at least 32 UTF-8 bytes before MGMA is enabled"
        )
    return pepper


def validate_pepper_for_mode(mode: Union[MgmaAccessMode, str]) -> None:
    mode = MgmaAccessMode(mode)
    if mode in (MgmaAccessMode.dual, MgmaAccessMode.ephemeral):
        require_token_pepper()


def digest_token(token: str, pepper: Optional[str] = None) -> str:
    """Return the keyed digest persisted for a bearer token."""

    key = pepper if pepper is not None else require_token_pepper()
    return hmac.new(
        key.encode("utf-8"),
        token.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def build_public_subscription_url(token: str, base_url: Optional[str] = None) -> str:
    """Build the only response value that contains a clear-text MGMA token."""

    prefix = XRAY_SUBSCRIPTION_URL_PREFIX.rstrip("/")
    if prefix:
        prefix = prefix.replace("*", secrets.token_hex(8))
    elif base_url:
        prefix = base_url.rstrip("/")
    else:
        raise MgmaConfigurationError(
            "XRAY_SUBSCRIPTION_URL_PREFIX is required outside an HTTP request"
        )
    return (
        f"{prefix}/{XRAY_SUBSCRIPTION_PATH}/mgma"
        f"?token={quote(token, safe='')}"
    )


def _utc_naive(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_settings(db: Session) -> MgmaSettings:
    """Return the singleton row, creating conservative defaults if absent."""

    settings = db.get(MgmaSettings, MGMA_SETTINGS_ID)
    if settings is not None:
        return settings

    settings = MgmaSettings(
        id=MGMA_SETTINGS_ID,
        mode=MgmaAccessMode.legacy.value,
        ttl_seconds=180,
        single_use=False,
        source_mode=MgmaSourceMode.any.value,
        custom_cidrs=[],
    )
    db.add(settings)
    try:
        db.commit()
    except IntegrityError:
        # Another worker may have initialized the singleton concurrently.
        db.rollback()
        settings = db.get(MgmaSettings, MGMA_SETTINGS_ID)
        if settings is None:
            raise
        return settings
    db.refresh(settings)
    return settings


def _metadata_value(metadata: Mapping[str, object], section: str, key: str):
    nested = metadata.get(section)
    return nested.get(key) if isinstance(nested, dict) else None


def settings_response(settings: MgmaSettings) -> MgmaSettingsResponse:
    metadata = load_china_cidr_metadata()
    metadata_count = _metadata_value(metadata, "records", "cidrs")
    try:
        count = int(metadata_count) if metadata_count is not None else load_china_cidr_index().count
    except (TypeError, ValueError, MgmaConfigurationError):
        count = 0

    return MgmaSettingsResponse(
        mode=settings.mode,
        ttl_seconds=settings.ttl_seconds,
        single_use=settings.single_use,
        source_mode=settings.source_mode,
        custom_cidrs=settings.custom_cidrs or [],
        pepper_configured=pepper_is_configured(),
        cn_cidr_version=_metadata_value(metadata, "source", "serial"),
        cn_cidr_data_end_date=_metadata_value(metadata, "source", "data_end_date"),
        cn_cidr_count=count,
        cn_cidr_sha256=_metadata_value(metadata, "output", "sha256"),
        updated_at=settings.updated_at,
    )


def get_settings_response(db: Session) -> MgmaSettingsResponse:
    return settings_response(get_settings(db))


def update_settings(
    db: Session,
    values: Union[MgmaSettingsUpdate, Mapping[str, object]],
) -> MgmaSettingsResponse:
    """Validate and replace all configurable MGMA settings."""

    if not isinstance(values, MgmaSettingsUpdate):
        values = MgmaSettingsUpdate.model_validate(values)

    validate_pepper_for_mode(values.mode)
    if values.source_mode in (MgmaSourceMode.china, MgmaSourceMode.china_or_custom):
        # Enabling a China policy with a missing/corrupt file must fail closed at
        # configuration time, not surprise every subscriber later.
        load_china_cidr_index()

    settings = get_settings(db)
    settings.mode = values.mode.value
    settings.ttl_seconds = values.ttl_seconds
    settings.single_use = values.single_use
    settings.source_mode = values.source_mode.value
    settings.custom_cidrs = list(values.custom_cidrs)
    settings.updated_at = _utc_naive()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(settings)
    return settings_response(settings)


def _eligible_user(user: User, current_time: datetime) -> bool:
    status = user.status.value if isinstance(user.status, UserStatus) else str(user.status)
    if status not in (UserStatus.active.value, UserStatus.on_hold.value):
        return False
    if user.expire and user.expire <= current_time.replace(tzinfo=timezone.utc).timestamp():
        return False
    if user.data_limit and user.used_traffic >= user.data_limit:
        return False
    return True


def issue_token(
    db: Session,
    user: User,
    now: Optional[datetime] = None,
) -> MgmaTokenIssue:
    """Issue a token and atomically make every prior token for ``user`` stale."""

    issued_at = _utc_naive(now)
    if not _eligible_user(user, issued_at):
        raise MgmaUserIneligible("only active or on-hold users can receive an MGMA token")

    settings = get_settings(db)
    pepper = require_token_pepper()
    expires_at = issued_at + timedelta(seconds=settings.ttl_seconds)
    token = secrets.token_urlsafe(MGMA_TOKEN_BYTES)

    user.sub_access_token_digest = digest_token(token, pepper)
    user.sub_access_issued_at = issued_at
    user.sub_access_expires_at = expires_at
    user.sub_access_consumed_at = None
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)

    return MgmaTokenIssue(
        token=token,
        issued_at=_utc_aware(issued_at),
        expires_at=_utc_aware(expires_at),
        ttl_seconds=settings.ttl_seconds,
    )


def revoke_token(db: Session, user: User) -> None:
    """Immediately invalidate the latest MGMA token for a user."""

    user.sub_access_token_digest = None
    user.sub_access_issued_at = None
    user.sub_access_expires_at = None
    user.sub_access_consumed_at = None
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def normalize_ip(value: object) -> Optional[IPAddress]:
    if isinstance(value, (IPv4Address, IPv6Address)):
        address = value
    elif isinstance(value, str):
        try:
            address = ip_address(value.strip())
        except ValueError:
            return None
    else:
        return None

    # Treat IPv4-mapped IPv6 addresses like their canonical IPv4 address so
    # they match the same source policy on dual-stack hosts.
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def get_real_client_ip(request: Request) -> Optional[str]:
    """Resolve a source IP without trusting user-controlled forwarding chains.

    Uvicorn behind the production Unix socket has ``request.client is None``;
    only in that case do we trust Nginx's overwritten ``X-Real-IP``. For a TCP
    listener, the actual peer address wins and all forwarding headers are
    ignored. Deployments proxying to TCP must not enable source restrictions
    unless the peer itself is the intended source.
    """

    if request.client is None:
        raw_address = request.headers.get("x-real-ip")
    else:
        raw_address = request.client.host

    address = normalize_ip(raw_address)
    return str(address) if address is not None else None


@lru_cache(maxsize=128)
def _custom_cidr_index(cidrs: tuple[str, ...]) -> CidrIndex:
    return _parse_cidrs(cidrs)


def source_allowed(
    source_ip: object,
    settings: Union[MgmaSettings, MgmaSettingsUpdate, MgmaSettingsResponse],
) -> bool:
    """Evaluate a configured source policy; restricted policies fail closed."""

    mode = MgmaSourceMode(settings.source_mode)
    if mode == MgmaSourceMode.any:
        return True

    address = normalize_ip(source_ip)
    if address is None:
        return False

    custom_match = False
    if mode in (MgmaSourceMode.custom, MgmaSourceMode.china_or_custom):
        try:
            custom_match = _custom_cidr_index(tuple(settings.custom_cidrs or ())).contains(address)
        except (TypeError, ValueError, MgmaConfigurationError):
            custom_match = False

    china_match = False
    if mode in (MgmaSourceMode.china, MgmaSourceMode.china_or_custom):
        try:
            china_match = load_china_cidr_index().contains(address)
        except MgmaConfigurationError:
            china_match = False

    if mode == MgmaSourceMode.custom:
        return custom_match
    if mode == MgmaSourceMode.china:
        return china_match
    return china_match or custom_match


def validate_token(
    db: Session,
    token: str,
    source_ip: object,
    *,
    consume: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> User:
    """Validate an MGMA token and optionally consume it atomically.

    The same opaque exception is raised for every public validation failure.
    By default, consumption follows the global ``single_use`` setting.
    """

    if not isinstance(token, str) or not MGMA_TOKEN_RE.fullmatch(token):
        raise MgmaTokenRejected()

    try:
        digest = digest_token(token)
    except (UnicodeError, MgmaConfigurationError):
        raise MgmaTokenRejected() from None

    settings = get_settings(db)
    if not source_allowed(source_ip, settings):
        raise MgmaTokenRejected()

    user = db.query(User).filter(User.sub_access_token_digest == digest).first()
    current_time = _utc_naive(now)
    if (
        user is None
        or not hmac.compare_digest(user.sub_access_token_digest or "", digest)
        or user.sub_access_issued_at is None
        or user.sub_access_expires_at is None
        or user.sub_access_expires_at <= current_time
        or (
            user.sub_revoked_at is not None
            and user.sub_access_issued_at <= user.sub_revoked_at
        )
        or not _eligible_user(user, current_time)
    ):
        raise MgmaTokenRejected()

    should_consume = settings.single_use if consume is None else consume
    if should_consume:
        result = db.execute(
            update(User)
            .where(
                User.id == user.id,
                User.sub_access_token_digest == digest,
                User.sub_access_expires_at > current_time,
                User.sub_access_consumed_at.is_(None),
            )
            .values(sub_access_consumed_at=current_time)
        )
        if result.rowcount != 1:
            db.rollback()
            raise MgmaTokenRejected()
        db.commit()
        db.refresh(user)
    elif user.sub_access_consumed_at is not None:
        # A token consumed while single-use was enabled stays consumed even if
        # the setting is later relaxed during its short lifetime.
        raise MgmaTokenRejected()

    return user
