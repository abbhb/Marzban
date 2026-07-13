"""Invitation-only registration and persistent source-IP protection."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import Optional

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.db.models import (
    PortalIPBlock,
    PortalInvitationCode,
    PortalInvitationUse,
    PortalSecurityAttempt,
    PortalSecuritySettings,
)


class PortalSecurityError(Exception):
    pass


class InvitationUnavailable(PortalSecurityError):
    pass


class InvitationConfigurationError(PortalSecurityError):
    pass


class IPBlockConfigurationError(PortalSecurityError):
    pass


LOGIN_KINDS = {"portal_login", "admin_login"}
REGISTRATION_KIND = "portal_registration"
FAILURE_KINDS = LOGIN_KINDS | {REGISTRATION_KIND}
MAX_ATTEMPT_ROWS = 10_000


def utc_now(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_source_ip(value: object) -> Optional[str]:
    try:
        address = ip_address(str(value).strip())
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return str(address)


def normalize_network(value: str) -> str:
    try:
        network = ip_network(value.strip(), strict=False)
    except ValueError as exc:
        raise IPBlockConfigurationError("Enter a valid IPv4/IPv6 address or CIDR") from exc
    if isinstance(network.network_address, IPv6Address) and network.network_address.ipv4_mapped:
        mapped = network.network_address.ipv4_mapped
        prefix = max(0, network.prefixlen - 96)
        network = ip_network(f"{mapped}/{prefix}", strict=False)
    return str(network)


def exact_network(source_ip: str) -> str:
    address = ip_address(source_ip)
    prefix = 32 if isinstance(address, IPv4Address) else 128
    return f"{address}/{prefix}"


def invitation_digest(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _validate_invitation_window(
    *,
    valid_from: Optional[datetime],
    expires_at: Optional[datetime],
    max_uses: Optional[int],
) -> tuple[Optional[datetime], Optional[datetime]]:
    valid_from = utc_now(valid_from) if valid_from else None
    expires_at = utc_now(expires_at) if expires_at else None
    if valid_from and expires_at and expires_at <= valid_from:
        raise InvitationConfigurationError("Invitation expiry must be after its start time")
    if max_uses is not None and not 1 <= max_uses <= 1_000_000:
        raise InvitationConfigurationError("Invitation usage limit must be between 1 and 1000000")
    return valid_from, expires_at


def create_invitation(
    db: Session,
    *,
    created_by: str,
    note: str = "",
    valid_from: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    max_uses: Optional[int] = 1,
) -> tuple[PortalInvitationCode, str]:
    valid_from, expires_at = _validate_invitation_window(
        valid_from=valid_from,
        expires_at=expires_at,
        max_uses=max_uses,
    )
    code = f"MGMA-{secrets.token_urlsafe(32)}"
    invitation = PortalInvitationCode(
        code_digest=invitation_digest(code),
        code_prefix=code[:12],
        note=note.strip(),
        valid_from=valid_from,
        expires_at=expires_at,
        max_uses=max_uses,
        created_by=created_by,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, code


def list_invitations(db: Session, *, limit: int = 500) -> list[PortalInvitationCode]:
    return (
        db.query(PortalInvitationCode)
        .order_by(PortalInvitationCode.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def get_invitation(db: Session, invitation_id: int) -> Optional[PortalInvitationCode]:
    return (
        db.query(PortalInvitationCode)
        .filter(PortalInvitationCode.id == invitation_id)
        .first()
    )


def disable_invitation(
    db: Session,
    invitation: PortalInvitationCode,
) -> PortalInvitationCode:
    invitation.is_active = False
    invitation.updated_at = utc_now()
    db.commit()
    db.refresh(invitation)
    return invitation


def ensure_invitation_available(
    db: Session,
    code: str,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Reject unavailable capabilities before revealing account conflicts.

    Consumption still uses a conditional UPDATE, so this preflight check does
    not weaken the concurrent max-use guarantee.
    """

    now = utc_now(now)
    invitation = (
        db.query(PortalInvitationCode.id)
        .filter(
            PortalInvitationCode.code_digest == invitation_digest(code),
            PortalInvitationCode.is_active.is_(True),
            or_(PortalInvitationCode.valid_from.is_(None), PortalInvitationCode.valid_from <= now),
            or_(PortalInvitationCode.expires_at.is_(None), PortalInvitationCode.expires_at > now),
            or_(
                PortalInvitationCode.max_uses.is_(None),
                PortalInvitationCode.use_count < PortalInvitationCode.max_uses,
            ),
        )
        .first()
    )
    if not invitation:
        raise InvitationUnavailable


def consume_invitation(
    db: Session,
    code: str,
    *,
    now: Optional[datetime] = None,
) -> PortalInvitationCode:
    now = utc_now(now)
    digest = invitation_digest(code)
    invitation = (
        db.query(PortalInvitationCode)
        .filter(PortalInvitationCode.code_digest == digest)
        .first()
    )
    if not invitation:
        raise InvitationUnavailable

    conditions = [
        PortalInvitationCode.id == invitation.id,
        PortalInvitationCode.is_active.is_(True),
        or_(PortalInvitationCode.valid_from.is_(None), PortalInvitationCode.valid_from <= now),
        or_(PortalInvitationCode.expires_at.is_(None), PortalInvitationCode.expires_at > now),
        or_(
            PortalInvitationCode.max_uses.is_(None),
            PortalInvitationCode.use_count < PortalInvitationCode.max_uses,
        ),
    ]
    updated = db.execute(
        update(PortalInvitationCode)
        .where(*conditions)
        .values(
            use_count=PortalInvitationCode.use_count + 1,
            last_used_at=now,
            updated_at=now,
        )
    )
    if updated.rowcount != 1:
        raise InvitationUnavailable
    db.flush()
    db.refresh(invitation)
    return invitation


def add_invitation_use(
    db: Session,
    *,
    invitation_id: int,
    account_id: int,
    source_ip: str,
    now: Optional[datetime] = None,
) -> PortalInvitationUse:
    row = PortalInvitationUse(
        invitation_id=invitation_id,
        account_id=account_id,
        source_ip=source_ip,
        used_at=utc_now(now),
    )
    db.add(row)
    db.flush()
    return row


def get_security_settings(db: Session) -> PortalSecuritySettings:
    settings = db.query(PortalSecuritySettings).filter(PortalSecuritySettings.id == 1).first()
    if settings:
        return settings
    settings = PortalSecuritySettings(id=1)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def update_security_settings(db: Session, changes: dict) -> PortalSecuritySettings:
    settings = get_security_settings(db)
    for key, value in changes.items():
        setattr(settings, key, value)
    settings.updated_at = utc_now()
    db.commit()
    db.refresh(settings)
    return settings


def list_blocks(db: Session, *, limit: int = 500) -> list[PortalIPBlock]:
    return (
        db.query(PortalIPBlock)
        .order_by(PortalIPBlock.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def get_block(db: Session, block_id: int) -> Optional[PortalIPBlock]:
    return db.query(PortalIPBlock).filter(PortalIPBlock.id == block_id).first()


def add_block(
    db: Session,
    *,
    network: str,
    reason: str,
    source: str,
    created_by: str,
    expires_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    commit: bool = True,
) -> PortalIPBlock:
    now = utc_now(now)
    network = normalize_network(network)
    reason = reason.strip()
    if not reason:
        raise IPBlockConfigurationError("A blacklist reason is required")
    expires_at = utc_now(expires_at) if expires_at else None
    if expires_at and expires_at <= now:
        raise IPBlockConfigurationError("Blacklist expiry must be in the future")

    block = db.query(PortalIPBlock).filter(PortalIPBlock.network == network).first()
    if block:
        block.reason = reason
        block.source = source
        block.is_active = True
        block.expires_at = expires_at
        block.created_by = created_by
        block.updated_at = now
        block.revoked_at = None
        block.revoked_by = None
    else:
        block = PortalIPBlock(
            network=network,
            reason=reason,
            source=source,
            expires_at=expires_at,
            created_by=created_by,
        )
        db.add(block)
    if commit:
        db.commit()
        db.refresh(block)
    else:
        db.flush()
    return block


def revoke_block(
    db: Session,
    block: PortalIPBlock,
    *,
    revoked_by: str,
    now: Optional[datetime] = None,
) -> PortalIPBlock:
    now = utc_now(now)
    block.is_active = False
    block.revoked_at = now
    block.revoked_by = revoked_by
    block.updated_at = now

    network = ip_network(block.network)
    if network.prefixlen == network.max_prefixlen:
        db.query(PortalSecurityAttempt).filter(
            PortalSecurityAttempt.source_ip == str(network.network_address)
        ).delete(synchronize_session=False)
    db.commit()
    db.refresh(block)
    return block


def find_active_block(
    db: Session,
    source_ip: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[PortalIPBlock]:
    normalized = normalize_source_ip(source_ip)
    if not normalized:
        return None
    address = ip_address(normalized)
    now = utc_now(now)
    candidates = (
        db.query(PortalIPBlock)
        .filter(
            PortalIPBlock.is_active.is_(True),
            or_(PortalIPBlock.expires_at.is_(None), PortalIPBlock.expires_at > now),
        )
        .all()
    )
    for block in candidates:
        try:
            if address in ip_network(block.network):
                return block
        except ValueError:
            continue
    return None


def _failure_policy(
    settings: PortalSecuritySettings,
    kind: str,
) -> tuple[int, int]:
    if kind in LOGIN_KINDS:
        return settings.login_failure_limit, settings.login_window_seconds
    if kind == REGISTRATION_KIND:
        return settings.registration_failure_limit, settings.registration_window_seconds
    raise ValueError(f"Unsupported portal security failure kind: {kind}")


def _ensure_attempt_capacity(
    db: Session,
    *,
    settings: PortalSecuritySettings,
    now: datetime,
) -> None:
    """Keep attacker-controlled persistent counter cardinality bounded."""

    count = db.query(PortalSecurityAttempt.id).count()
    if count < MAX_ATTEMPT_ROWS:
        return
    cutoff = now - timedelta(
        seconds=max(settings.login_window_seconds, settings.registration_window_seconds)
    )
    db.query(PortalSecurityAttempt).filter(
        PortalSecurityAttempt.last_failed_at <= cutoff
    ).delete(synchronize_session=False)
    count = db.query(PortalSecurityAttempt.id).count()
    overflow = count - MAX_ATTEMPT_ROWS + 1
    if overflow > 0:
        oldest = [
            row[0]
            for row in (
                db.query(PortalSecurityAttempt.id)
                .order_by(PortalSecurityAttempt.last_failed_at.asc())
                .limit(overflow)
                .all()
            )
        ]
        if oldest:
            db.query(PortalSecurityAttempt).filter(
                PortalSecurityAttempt.id.in_(oldest)
            ).delete(synchronize_session=False)


def record_failure(
    db: Session,
    *,
    source_ip: str,
    kind: str,
    now: Optional[datetime] = None,
) -> Optional[PortalIPBlock]:
    normalized = normalize_source_ip(source_ip)
    if not normalized or kind not in FAILURE_KINDS:
        return None
    now = utc_now(now)
    settings = get_security_settings(db)
    limit, window_seconds = _failure_policy(settings, kind)
    attempt = (
        db.query(PortalSecurityAttempt)
        .filter(
            PortalSecurityAttempt.source_ip == normalized,
            PortalSecurityAttempt.kind == kind,
        )
        .first()
    )
    cutoff = now - timedelta(seconds=window_seconds)
    if not attempt:
        _ensure_attempt_capacity(db, settings=settings, now=now)
        attempt = PortalSecurityAttempt(
            source_ip=normalized,
            kind=kind,
            failure_count=1,
            window_started_at=now,
            last_failed_at=now,
        )
        db.add(attempt)
    elif attempt.window_started_at <= cutoff:
        attempt.failure_count = 1
        attempt.window_started_at = now
        attempt.last_failed_at = now
    else:
        attempt.failure_count += 1
        attempt.last_failed_at = now
    db.flush()

    block = None
    if settings.auto_block_enabled and attempt.failure_count >= limit:
        labels = {
            "portal_login": "portal login",
            "admin_login": "administrator login",
            "portal_registration": "portal registration/invitation",
        }
        expires_at = (
            now + timedelta(seconds=settings.auto_block_seconds)
            if settings.auto_block_seconds
            else None
        )
        block = add_block(
            db,
            network=exact_network(normalized),
            reason=(
                f"Automatic block: {attempt.failure_count} failed {labels[kind]} "
                f"attempts within {window_seconds} seconds"
            ),
            source=kind,
            created_by="system",
            expires_at=expires_at,
            now=now,
            commit=False,
        )
    db.commit()
    if block:
        db.refresh(block)
    return block


def reset_failures(db: Session, *, source_ip: str, kind: str) -> None:
    normalized = normalize_source_ip(source_ip)
    if not normalized:
        return
    db.query(PortalSecurityAttempt).filter(
        PortalSecurityAttempt.source_ip == normalized,
        PortalSecurityAttempt.kind == kind,
    ).delete(synchronize_session=False)
    db.commit()
