"""Transactional portal, wallet and subscription-plan operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import xray
from app.db.models import (
    PortalAccount,
    PortalPurchase,
    PortalSubscription,
    Proxy,
    ProxyHost,
    ProxyInbound,
    SubscriptionPlan,
    User,
    UserUsageResetLogs,
    WalletTransaction,
)
from app.models.admin import pwd_context
from app.models.commerce import (
    PortalAccountListStatus,
    PortalAccountAdminResponse,
    PortalMeResponse,
    PortalRegister,
    PortalSubscriptionResponse,
    PortalUsageResponse,
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
)
from app.models.proxy import ProxyTypes, VLESSSettings
from app.models.user import UserDataLimitResetStrategy, UserStatus
from app.services import portal_security


class CommerceError(Exception):
    """Base error mapped to a stable API response by the router."""


class AccountExists(CommerceError):
    pass


class AccountUnavailable(CommerceError):
    pass


class PlanUnavailable(CommerceError):
    pass


class PlanConfigurationError(CommerceError):
    pass


class InsufficientBalance(CommerceError):
    pass


class SubscriptionUnavailable(CommerceError):
    pass


class IdempotencyConflict(CommerceError):
    pass


@dataclass
class PlanApplication:
    account: PortalAccount
    purchase: PortalPurchase
    user: User
    created_user: bool
    replayed: bool = False


def utc_now(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def account_query(db: Session):
    return db.query(PortalAccount).options(
        joinedload(PortalAccount.subscription).joinedload(PortalSubscription.plan),
        joinedload(PortalAccount.proxy_user),
    )


def get_account(db: Session, account_id: int) -> Optional[PortalAccount]:
    return account_query(db).filter(PortalAccount.id == account_id).first()


def get_account_by_username(db: Session, username: str) -> Optional[PortalAccount]:
    return account_query(db).filter(PortalAccount.username == username).first()


def register_account(
    db: Session,
    values: PortalRegister,
    *,
    source_ip: str,
    now: Optional[datetime] = None,
) -> PortalAccount:
    now = utc_now(now)
    portal_security.ensure_invitation_available(
        db,
        values.invitation_code,
        now=now,
    )

    if get_account_by_username(db, values.username) or db.query(User.id).filter(
        User.username == values.username
    ).first():
        raise AccountExists

    invitation = portal_security.consume_invitation(
        db,
        values.invitation_code,
        now=now,
    )

    account = PortalAccount(
        username=values.username,
        hashed_password=pwd_context.hash(values.password),
        wallet_balance_minor=0,
    )
    db.add(account)
    try:
        db.flush()
        portal_security.add_invitation_use(
            db,
            invitation_id=invitation.id,
            account_id=account.id,
            source_ip=source_ip,
            now=now,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AccountExists from exc
    db.refresh(account)
    return get_account(db, account.id)


def authenticate_account(db: Session, username: str, password: str) -> Optional[PortalAccount]:
    account = get_account_by_username(db, username)
    if not account or not account.is_active:
        return None
    try:
        valid = pwd_context.verify(password, account.hashed_password)
    except ValueError:
        valid = False
    return account if valid else None


def _plan_protocol(tag: str) -> Optional[str]:
    inbound = xray.config.inbounds_by_tag.get(tag)
    if not inbound:
        return None
    protocol = inbound.get("protocol")
    return protocol.value if hasattr(protocol, "value") else str(protocol)


def validate_plan_inbounds(tags: Iterable[str]) -> list[str]:
    values = list(tags)
    invalid = [tag for tag in values if _plan_protocol(tag) != ProxyTypes.VLESS.value]
    if invalid:
        raise PlanConfigurationError(
            "Plans may contain existing VLESS inbound tags only: " + ", ".join(invalid)
        )
    return values


def create_plan(db: Session, values: SubscriptionPlanCreate) -> SubscriptionPlan:
    validate_plan_inbounds(values.inbound_tags)
    plan = SubscriptionPlan(**values.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(
    db: Session,
    plan: SubscriptionPlan,
    values: SubscriptionPlanUpdate,
) -> SubscriptionPlan:
    changes = values.model_dump(exclude_unset=True)
    if "inbound_tags" in changes:
        validate_plan_inbounds(changes["inbound_tags"])
    for field, value in changes.items():
        setattr(plan, field, value)
    plan.updated_at = utc_now()
    db.commit()
    db.refresh(plan)
    return plan


def get_plan(db: Session, plan_id: int) -> Optional[SubscriptionPlan]:
    return db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()


def list_plans(db: Session) -> list[SubscriptionPlan]:
    return db.query(SubscriptionPlan).order_by(SubscriptionPlan.id.desc()).all()


def visible_plans(db: Session) -> list[SubscriptionPlan]:
    return (
        db.query(SubscriptionPlan)
        .filter(SubscriptionPlan.is_visible.is_(True))
        .order_by(SubscriptionPlan.id.desc())
        .all()
    )


def usage_response(account: PortalAccount) -> PortalUsageResponse:
    user = account.proxy_user
    if not user:
        return PortalUsageResponse()
    return PortalUsageResponse(
        status=user.status,
        used_traffic=int(user.used_traffic or 0),
        data_limit=int(user.data_limit) if user.data_limit is not None else None,
        lifetime_used_traffic=int(user.lifetime_used_traffic),
        expire=user.expire,
    )


def me_response(account: PortalAccount) -> PortalMeResponse:
    return PortalMeResponse(
        id=account.id,
        username=account.username,
        wallet_balance_minor=int(account.wallet_balance_minor),
        is_active=account.is_active,
        user_id=account.user_id,
        created_at=account.created_at,
        subscription=subscription_response(account) if account.subscription else None,
        usage=usage_response(account),
    )


def admin_account_response(account: PortalAccount) -> PortalAccountAdminResponse:
    return PortalAccountAdminResponse(
        **me_response(account).model_dump(),
    )


def list_accounts(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    status: Optional[PortalAccountListStatus] = None,
) -> tuple[list[PortalAccount], int]:
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError("page must be positive and page_size must be between 1 and 100")

    query = db.query(PortalAccount)
    search = search.strip() if search else None
    if search:
        query = query.filter(PortalAccount.username.ilike(f"%{search}%"))

    if status == "not_activated":
        query = query.filter(PortalAccount.user_id.is_(None))
    elif status is not None:
        try:
            proxy_status = UserStatus(status)
        except ValueError as exc:
            raise ValueError(f"Unsupported portal account status: {status}") from exc
        query = query.join(PortalAccount.proxy_user).filter(User.status == proxy_status)

    # Count the filtered base query before eager loading. Applying joinedload to
    # a count query is both unnecessary and fragile across SQLAlchemy versions.
    total = query.order_by(None).count()
    items = (
        query.options(
            joinedload(PortalAccount.subscription).joinedload(PortalSubscription.plan),
            joinedload(PortalAccount.proxy_user).joinedload(User.usage_logs),
        )
        .order_by(PortalAccount.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def list_wallet_transactions(
    db: Session,
    account_id: int,
    *,
    limit: int = 100,
) -> list[WalletTransaction]:
    return (
        db.query(WalletTransaction)
        .filter(WalletTransaction.account_id == account_id)
        .order_by(WalletTransaction.id.desc())
        .limit(limit)
        .all()
    )


def recharge_wallet(
    db: Session,
    account: PortalAccount,
    *,
    amount_minor: int,
    actor_admin: str,
    note: Optional[str],
    idempotency_key: str,
) -> PortalAccount:
    previous = (
        db.query(WalletTransaction)
        .filter(
            WalletTransaction.account_id == account.id,
            WalletTransaction.kind == "admin_credit",
            WalletTransaction.idempotency_key == idempotency_key,
        )
        .first()
    )
    if previous:
        if previous.amount_minor != amount_minor or previous.actor_admin != actor_admin:
            raise IdempotencyConflict
        return get_account(db, account.id)

    db.execute(
        update(PortalAccount)
        .where(PortalAccount.id == account.id)
        .values(
            wallet_balance_minor=PortalAccount.wallet_balance_minor + amount_minor,
            updated_at=utc_now(),
        ),
        execution_options={"synchronize_session": False},
    )
    db.flush()
    db.refresh(account)
    db.add(
        WalletTransaction(
            account_id=account.id,
            amount_minor=amount_minor,
            balance_after_minor=account.wallet_balance_minor,
            kind="admin_credit",
            idempotency_key=idempotency_key,
            actor_admin=actor_admin,
            note=note,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.account_id == account.id,
                WalletTransaction.kind == "admin_credit",
                WalletTransaction.idempotency_key == idempotency_key,
            )
            .first()
        )
        if previous:
            if previous.amount_minor != amount_minor or previous.actor_admin != actor_admin:
                raise IdempotencyConflict
            return get_account(db, account.id)
        raise
    return get_account(db, account.id)


def _all_vless_tags() -> list[str]:
    return [
        inbound["tag"]
        for inbound in xray.config.inbounds_by_protocol.get(ProxyTypes.VLESS, [])
    ]


def _inbound_rows(db: Session, tags: Iterable[str]) -> dict[str, ProxyInbound]:
    tags = list(tags)
    rows = {
        row.tag: row
        for row in db.query(ProxyInbound).filter(ProxyInbound.tag.in_(tags)).all()
    }
    for tag in tags:
        if tag not in rows:
            rows[tag] = ProxyInbound(
                tag=tag,
                hosts=[
                    ProxyHost(
                        remark="🚀 Marz ({USERNAME}) [{PROTOCOL} - {TRANSPORT}]",
                        address="{SERVER_IP}",
                    )
                ],
            )
            db.add(rows[tag])
    db.flush()
    return rows


def _apply_proxy_plan(
    db: Session,
    account: PortalAccount,
    plan: SubscriptionPlan,
    *,
    expires_at: datetime,
    now: datetime,
) -> tuple[User, bool]:
    validate_plan_inbounds(plan.inbound_tags)
    all_vless_tags = _all_vless_tags()
    if not all_vless_tags or any(tag not in all_vless_tags for tag in plan.inbound_tags):
        raise PlanConfigurationError("The plan no longer matches the active VLESS inbounds")

    inbound_rows = _inbound_rows(db, all_vless_tags)
    excluded = [inbound_rows[tag] for tag in all_vless_tags if tag not in plan.inbound_tags]

    user = account.proxy_user
    created_user = user is None
    if created_user:
        if db.query(User.id).filter(User.username == account.username).first():
            raise AccountUnavailable("A proxy user already owns this username")
        proxy = Proxy(
            type=ProxyTypes.VLESS.value,
            settings=VLESSSettings().dict(no_obj=True),
            excluded_inbounds=excluded,
        )
        user = User(
            username=account.username,
            proxies=[proxy],
            status=UserStatus.active,
            used_traffic=0,
            data_limit=plan.data_limit or None,
            data_limit_reset_strategy=UserDataLimitResetStrategy.no_reset,
            expire=int(expires_at.replace(tzinfo=timezone.utc).timestamp()),
            created_at=now,
            note=f"Self-service portal account #{account.id}",
            last_status_change=now,
        )
        db.add(user)
        db.flush()
        account.user_id = user.id
        account.proxy_user = user
    else:
        if user.used_traffic:
            db.add(
                UserUsageResetLogs(
                    user=user,
                    used_traffic_at_reset=user.used_traffic,
                    reset_at=now,
                )
            )
        user.used_traffic = 0
        user.data_limit = plan.data_limit or None
        user.data_limit_reset_strategy = UserDataLimitResetStrategy.no_reset
        user.expire = int(expires_at.replace(tzinfo=timezone.utc).timestamp())
        user.status = UserStatus.active
        user.on_hold_expire_duration = None
        user.on_hold_timeout = None
        user.last_status_change = now
        user.edit_at = now

        vless_proxies = [
            proxy for proxy in user.proxies if ProxyTypes(proxy.type) == ProxyTypes.VLESS
        ]
        if vless_proxies:
            proxy = vless_proxies[0]
            for duplicate in vless_proxies[1:]:
                db.delete(duplicate)
        else:
            proxy = Proxy(
                type=ProxyTypes.VLESS.value,
                settings=VLESSSettings().dict(no_obj=True),
            )
            user.proxies.append(proxy)
        for other in list(user.proxies):
            if other is not proxy and ProxyTypes(other.type) != ProxyTypes.VLESS:
                db.delete(other)
        proxy.excluded_inbounds = excluded

    account.updated_at = now
    return user, created_user


def _overwrite_subscription(
    account: PortalAccount,
    plan: SubscriptionPlan,
    *,
    amount_minor: int,
    now: datetime,
    expires_at: datetime,
) -> PortalSubscription:
    subscription = account.subscription
    if not subscription:
        subscription = PortalSubscription(account=account)
    subscription.plan = plan
    subscription.plan_name = plan.name
    subscription.price_paid_minor = amount_minor
    subscription.currency = plan.currency
    subscription.duration_days = plan.duration_days
    subscription.data_limit = plan.data_limit
    subscription.inbound_tags = list(plan.inbound_tags)
    subscription.starts_at = now
    subscription.expires_at = expires_at
    subscription.purchased_at = now
    subscription.disabled_at = None
    subscription.updated_at = now
    return subscription


def _purchase_response_from_record(
    db: Session,
    account_id: int,
    purchase: PortalPurchase,
) -> PlanApplication:
    account = get_account(db, account_id)
    if not account or not account.subscription or not account.proxy_user:
        raise SubscriptionUnavailable
    return PlanApplication(
        account=account,
        purchase=purchase,
        user=account.proxy_user,
        created_user=False,
        replayed=True,
    )


def purchase_plan(
    db: Session,
    account: PortalAccount,
    *,
    plan_id: int,
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> PlanApplication:
    previous = (
        db.query(PortalPurchase)
        .filter(
            PortalPurchase.account_id == account.id,
            PortalPurchase.idempotency_key == idempotency_key,
        )
        .first()
    )
    if previous:
        if previous.kind != "self_purchase" or previous.plan_id != plan_id:
            raise IdempotencyConflict
        return _purchase_response_from_record(db, account.id, previous)

    plan = get_plan(db, plan_id)
    if not account.is_active or not plan or not plan.is_visible:
        raise PlanUnavailable

    debit = db.execute(
        update(PortalAccount)
        .where(
            PortalAccount.id == account.id,
            PortalAccount.wallet_balance_minor >= plan.price_minor,
        )
        .values(
            wallet_balance_minor=PortalAccount.wallet_balance_minor - plan.price_minor,
            updated_at=utc_now(now),
        ),
        execution_options={"synchronize_session": False},
    )
    if debit.rowcount != 1:
        db.rollback()
        raise InsufficientBalance

    now = utc_now(now)
    expires_at = now + timedelta(days=plan.duration_days)
    db.flush()
    db.refresh(account)
    balance_after = int(account.wallet_balance_minor)
    balance_before = balance_after + int(plan.price_minor)

    user, created_user = _apply_proxy_plan(
        db,
        account,
        plan,
        expires_at=expires_at,
        now=now,
    )
    subscription = _overwrite_subscription(
        account,
        plan,
        amount_minor=plan.price_minor,
        now=now,
        expires_at=expires_at,
    )
    db.add(subscription)
    purchase = PortalPurchase(
        account=account,
        plan=plan,
        kind="self_purchase",
        idempotency_key=idempotency_key,
        plan_name=plan.name,
        amount_minor=plan.price_minor,
        currency=plan.currency,
        duration_days=plan.duration_days,
        data_limit=plan.data_limit,
        inbound_tags=list(plan.inbound_tags),
        balance_before_minor=balance_before,
        balance_after_minor=balance_after,
        effective_expires_at=expires_at,
        created_at=now,
    )
    db.add(purchase)
    db.flush()
    if plan.price_minor:
        db.add(
            WalletTransaction(
                account=account,
                amount_minor=-plan.price_minor,
                balance_after_minor=balance_after,
                kind="purchase_debit",
                purchase=purchase,
                note=f"Purchase: {plan.name}",
                created_at=now,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = (
            db.query(PortalPurchase)
            .filter(
                PortalPurchase.account_id == account.id,
                PortalPurchase.idempotency_key == idempotency_key,
            )
            .first()
        )
        if previous:
            if previous.kind != "self_purchase" or previous.plan_id != plan_id:
                raise IdempotencyConflict
            return _purchase_response_from_record(db, account.id, previous)
        raise

    account = get_account(db, account.id)
    return PlanApplication(
        account=account,
        purchase=purchase,
        user=account.proxy_user,
        created_user=created_user,
    )


def grant_plan(
    db: Session,
    account: PortalAccount,
    plan: SubscriptionPlan,
    *,
    actor_admin: str,
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> PlanApplication:
    previous = (
        db.query(PortalPurchase)
        .filter(
            PortalPurchase.account_id == account.id,
            PortalPurchase.idempotency_key == idempotency_key,
        )
        .first()
    )
    if previous:
        if previous.kind != "admin_grant" or previous.plan_id != plan.id:
            raise IdempotencyConflict
        return _purchase_response_from_record(db, account.id, previous)

    now = utc_now(now)
    expires_at = now + timedelta(days=plan.duration_days)
    user, created_user = _apply_proxy_plan(
        db,
        account,
        plan,
        expires_at=expires_at,
        now=now,
    )
    subscription = _overwrite_subscription(
        account,
        plan,
        amount_minor=0,
        now=now,
        expires_at=expires_at,
    )
    db.add(subscription)
    purchase = PortalPurchase(
        account=account,
        plan=plan,
        kind="admin_grant",
        idempotency_key=idempotency_key,
        actor_admin=actor_admin,
        plan_name=plan.name,
        amount_minor=0,
        currency=plan.currency,
        duration_days=plan.duration_days,
        data_limit=plan.data_limit,
        inbound_tags=list(plan.inbound_tags),
        balance_before_minor=account.wallet_balance_minor,
        balance_after_minor=account.wallet_balance_minor,
        effective_expires_at=expires_at,
        created_at=now,
    )
    db.add(purchase)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = (
            db.query(PortalPurchase)
            .filter(
                PortalPurchase.account_id == account.id,
                PortalPurchase.idempotency_key == idempotency_key,
            )
            .first()
        )
        if previous:
            if previous.kind != "admin_grant" or previous.plan_id != plan.id:
                raise IdempotencyConflict
            return _purchase_response_from_record(db, account.id, previous)
        raise
    account = get_account(db, account.id)
    return PlanApplication(
        account=account,
        purchase=purchase,
        user=account.proxy_user,
        created_user=created_user,
    )


def renew_subscription(
    db: Session,
    account: PortalAccount,
    *,
    days: int,
    actor_admin: str,
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> PlanApplication:
    previous = (
        db.query(PortalPurchase)
        .filter(
            PortalPurchase.account_id == account.id,
            PortalPurchase.idempotency_key == idempotency_key,
        )
        .first()
    )
    if previous:
        if previous.kind != "admin_renewal" or previous.duration_days != days:
            raise IdempotencyConflict
        return _purchase_response_from_record(db, account.id, previous)

    now = utc_now(now)
    subscription = account.subscription
    user = account.proxy_user
    if not subscription or not user:
        raise SubscriptionUnavailable
    plan = get_plan(db, subscription.plan_id)
    if not plan:
        raise PlanUnavailable

    base = subscription.expires_at if subscription.expires_at > now else now
    expires_at = base + timedelta(days=days)
    subscription.expires_at = expires_at
    subscription.duration_days += days
    subscription.updated_at = now
    user.expire = int(expires_at.replace(tzinfo=timezone.utc).timestamp())
    if user.status == UserStatus.expired:
        user.status = UserStatus.active
        user.last_status_change = now
    user.edit_at = now
    purchase = PortalPurchase(
        account=account,
        plan=plan,
        kind="admin_renewal",
        idempotency_key=idempotency_key,
        actor_admin=actor_admin,
        plan_name=plan.name,
        amount_minor=0,
        currency=subscription.currency,
        duration_days=days,
        data_limit=subscription.data_limit,
        inbound_tags=list(subscription.inbound_tags),
        balance_before_minor=account.wallet_balance_minor,
        balance_after_minor=account.wallet_balance_minor,
        effective_expires_at=expires_at,
        created_at=now,
    )
    db.add(purchase)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = (
            db.query(PortalPurchase)
            .filter(
                PortalPurchase.account_id == account.id,
                PortalPurchase.idempotency_key == idempotency_key,
            )
            .first()
        )
        if previous:
            if previous.kind != "admin_renewal" or previous.duration_days != days:
                raise IdempotencyConflict
            return _purchase_response_from_record(db, account.id, previous)
        raise
    account = get_account(db, account.id)
    return PlanApplication(
        account=account,
        purchase=purchase,
        user=account.proxy_user,
        created_user=False,
    )


def disable_subscription(
    db: Session,
    account: PortalAccount,
    *,
    now: Optional[datetime] = None,
) -> User:
    now = utc_now(now)
    if not account.subscription or not account.proxy_user:
        raise SubscriptionUnavailable
    account.subscription.disabled_at = now
    account.subscription.updated_at = now
    account.proxy_user.status = UserStatus.disabled
    account.proxy_user.last_status_change = now
    account.proxy_user.edit_at = now
    db.commit()
    return account.proxy_user


def subscription_response(account: PortalAccount) -> PortalSubscriptionResponse:
    subscription = account.subscription
    if not subscription:
        raise SubscriptionUnavailable
    response = PortalSubscriptionResponse.model_validate(subscription)
    if subscription.plan:
        response.plan_name = subscription.plan.name
    return response
