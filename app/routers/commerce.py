"""Self-service portal and sudo-only commerce administration APIs."""

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError

from app import xray
from app.db import Session, get_db
from app.db.models import PortalAccount, SubscriptionPlan
from app.dependencies import get_current_portal_account
from app.models.admin import Admin
from app.models.commerce import (
    AdminGrantPlanRequest,
    AdminRenewSubscriptionRequest,
    IPBlockCreate,
    IPBlockResponse,
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationResponse,
    PortalAccountAdminResponse,
    PortalAccountResponse,
    PortalMeResponse,
    PortalPurchaseRequest,
    PortalPurchaseResponse,
    PortalRegister,
    PortalToken,
    PortalSecuritySettingsResponse,
    PortalSecuritySettingsUpdate,
    SubscriptionPlanCreate,
    SubscriptionPlanResponse,
    SubscriptionPlanUpdate,
    WalletRechargeRequest,
    WalletTransactionResponse,
)
from app.models.mgma import MgmaIssueResponse
from app.models.user import UserStatus
from app.services import commerce, portal_security
from app.services.mgma import (
    MgmaConfigurationError,
    MgmaUserIneligible,
    build_public_subscription_url,
    issue_token,
    revoke_token,
)
from app.services.rate_limit import SlidingWindowLimiter
from app.utils.jwt import create_portal_token


router = APIRouter(tags=["Portal Commerce"])

NO_STORE_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Referrer-Policy": "no-referrer",
}
PORTAL_RATE_LIMITER = SlidingWindowLimiter()


def _validate_idempotency_key(value: str) -> str:
    if not 8 <= len(value) <= 128 or any(char.isspace() for char in value):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must contain 8 to 128 non-whitespace characters",
        )
    return value


def _rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    retry_after = PORTAL_RATE_LIMITER.hit(
        key,
        limit=limit,
        window_seconds=window_seconds,
    )
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )


def _client_key(request: Request) -> str:
    from app.services.mgma import get_real_client_ip

    return get_real_client_ip(request) or "unknown"


def _get_account_or_404(db: Session, account_id: int) -> PortalAccount:
    account = commerce.get_account(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Portal account not found")
    return account


def _get_plan_or_404(db: Session, plan_id: int) -> SubscriptionPlan:
    plan = commerce.get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    return plan


def _get_invitation_or_404(db: Session, invitation_id: int):
    invitation = portal_security.get_invitation(db, invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return invitation


def _get_block_or_404(db: Session, block_id: int):
    block = portal_security.get_block(db, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Blacklist entry not found")
    return block


def _sync_proxy(bg: BackgroundTasks, result: commerce.PlanApplication) -> None:
    if result.replayed:
        return
    if result.user.status not in (UserStatus.active, UserStatus.on_hold):
        bg.add_task(xray.operations.remove_user_by_id, user_id=result.user.id)
        return
    operation = (
        xray.operations.add_user_by_id
        if result.created_user
        else xray.operations.update_user_by_id
    )
    bg.add_task(operation, user_id=result.user.id)


def _purchase_response(result: commerce.PlanApplication) -> PortalPurchaseResponse:
    return PortalPurchaseResponse(
        purchase_id=result.purchase.id,
        replayed=result.replayed,
        wallet_balance_minor=result.account.wallet_balance_minor,
        subscription=commerce.subscription_response(result.account),
        usage=commerce.usage_response(result.account),
    )


@router.post(
    "/api/portal/register",
    response_model=PortalAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def portal_register(
    request: Request,
    values: PortalRegister,
    db: Session = Depends(get_db),
):
    client_key = _client_key(request)
    _rate_limit(
        f"portal-register:{client_key}",
        limit=5,
        window_seconds=60,
    )
    try:
        return commerce.register_account(db, values, source_ip=client_key)
    except portal_security.InvitationUnavailable:
        db.rollback()
        raise HTTPException(status_code=403, detail="portal.registrationUnavailable") from None
    except commerce.AccountExists:
        raise HTTPException(status_code=409, detail="Username is unavailable") from None


@router.post("/api/portal/token", response_model=PortalToken)
def portal_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    client_key = _client_key(request)
    username_key = f"portal-login-account:{client_key}:{form_data.username.casefold()}"
    _rate_limit(f"portal-login-ip:{client_key}", limit=60, window_seconds=300)
    _rate_limit(username_key, limit=5, window_seconds=300)
    account = commerce.authenticate_account(db, form_data.username, form_data.password)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    PORTAL_RATE_LIMITER.reset(username_key)
    return PortalToken(
        access_token=create_portal_token(account.id, account.username)
    )


@router.get("/api/portal/me", response_model=PortalMeResponse)
def portal_me(account: PortalAccount = Depends(get_current_portal_account)):
    return commerce.me_response(account)


@router.get("/api/portal/plans", response_model=List[SubscriptionPlanResponse])
def portal_plans(
    db: Session = Depends(get_db),
    _account: PortalAccount = Depends(get_current_portal_account),
):
    return commerce.visible_plans(db)


@router.get(
    "/api/portal/wallet/transactions",
    response_model=List[WalletTransactionResponse],
)
def portal_wallet_transactions(
    limit: int = 50,
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    limit = max(1, min(limit, 100))
    return commerce.list_wallet_transactions(db, account.id, limit=limit)


@router.post("/api/portal/purchase", response_model=PortalPurchaseResponse)
def portal_purchase(
    values: PortalPurchaseRequest,
    bg: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    idempotency_key = _validate_idempotency_key(idempotency_key)
    try:
        result = commerce.purchase_plan(
            db,
            account,
            plan_id=values.plan_id,
            idempotency_key=idempotency_key,
        )
    except commerce.InsufficientBalance:
        raise HTTPException(status_code=409, detail="Insufficient wallet balance") from None
    except commerce.PlanUnavailable:
        raise HTTPException(status_code=403, detail="Plan is not available to this account") from None
    except commerce.PlanConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except commerce.AccountUnavailable as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except commerce.IdempotencyConflict:
        db.rollback()
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for another request") from None
    _sync_proxy(bg, result)
    return _purchase_response(result)


@router.post("/api/portal/mgma", response_model=MgmaIssueResponse)
def portal_issue_mgma(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    if not account.proxy_user:
        raise HTTPException(status_code=409, detail="No active subscription")
    try:
        issued = issue_token(db, account.proxy_user)
    except MgmaUserIneligible:
        raise HTTPException(status_code=409, detail="Subscription is not active") from None
    except MgmaConfigurationError:
        raise HTTPException(status_code=503, detail="MGMA is not configured") from None
    response.headers.update(NO_STORE_HEADERS)
    return MgmaIssueResponse(
        url=build_public_subscription_url(issued.token, base_url=str(request.base_url)),
        issued_at=issued.issued_at,
        expires_at=issued.expires_at,
        ttl_seconds=issued.ttl_seconds,
    )


@router.delete("/api/portal/mgma")
def portal_revoke_mgma(
    response: Response,
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    if account.proxy_user:
        revoke_token(db, account.proxy_user)
    response.headers.update(NO_STORE_HEADERS)
    return {"detail": "Temporary subscription URL revoked"}


@router.get(
    "/api/commerce/admin/plans",
    response_model=List[SubscriptionPlanResponse],
)
def admin_list_plans(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return commerce.list_plans(db)


@router.post(
    "/api/commerce/admin/plans",
    response_model=SubscriptionPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_plan(
    values: SubscriptionPlanCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        return commerce.create_plan(db, values)
    except commerce.PlanConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plan name already exists") from None


@router.put(
    "/api/commerce/admin/plans/{plan_id}",
    response_model=SubscriptionPlanResponse,
)
def admin_update_plan(
    plan_id: int,
    values: SubscriptionPlanUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    plan = _get_plan_or_404(db, plan_id)
    try:
        return commerce.update_plan(db, plan, values)
    except commerce.PlanConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plan name already exists") from None


@router.get(
    "/api/commerce/admin/invitations",
    response_model=List[InvitationResponse],
)
def admin_list_invitations(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return portal_security.list_invitations(db)


@router.post(
    "/api/commerce/admin/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_invitation(
    values: InvitationCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        invitation, code = portal_security.create_invitation(
            db,
            created_by=admin.username,
            note=values.note,
            valid_from=values.valid_from,
            expires_at=values.expires_at,
            max_uses=values.max_uses,
        )
    except portal_security.InvitationConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    data = InvitationResponse.model_validate(invitation).model_dump()
    return InvitationCreatedResponse(**data, code=code)


@router.post(
    "/api/commerce/admin/invitations/{invitation_id}/disable",
    response_model=InvitationResponse,
)
def admin_disable_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return portal_security.disable_invitation(
        db,
        _get_invitation_or_404(db, invitation_id),
    )


@router.get(
    "/api/commerce/admin/security/blocks",
    response_model=List[IPBlockResponse],
)
def admin_list_ip_blocks(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return portal_security.list_blocks(db)


@router.post(
    "/api/commerce/admin/security/blocks",
    response_model=IPBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_ip_block(
    values: IPBlockCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        return portal_security.add_block(
            db,
            network=values.network,
            reason=values.reason,
            source="manual",
            created_by=admin.username,
            expires_at=values.expires_at,
        )
    except portal_security.IPBlockConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post(
    "/api/commerce/admin/security/blocks/{block_id}/revoke",
    response_model=IPBlockResponse,
)
def admin_revoke_ip_block(
    block_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    return portal_security.revoke_block(
        db,
        _get_block_or_404(db, block_id),
        revoked_by=admin.username,
    )


@router.get(
    "/api/commerce/admin/security/settings",
    response_model=PortalSecuritySettingsResponse,
)
def admin_get_portal_security_settings(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return portal_security.get_security_settings(db)


@router.put(
    "/api/commerce/admin/security/settings",
    response_model=PortalSecuritySettingsResponse,
)
def admin_update_portal_security_settings(
    values: PortalSecuritySettingsUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return portal_security.update_security_settings(db, values.model_dump())


@router.get(
    "/api/commerce/admin/accounts",
    response_model=List[PortalAccountAdminResponse],
)
def admin_list_accounts(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return [commerce.admin_account_response(account) for account in commerce.list_accounts(db)]


@router.post(
    "/api/commerce/admin/accounts/{account_id}/wallet/recharge",
    response_model=PortalAccountAdminResponse,
)
def admin_recharge_wallet(
    account_id: int,
    values: WalletRechargeRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    idempotency_key = _validate_idempotency_key(idempotency_key)
    account = _get_account_or_404(db, account_id)
    try:
        account = commerce.recharge_wallet(
            db,
            account,
            amount_minor=values.amount_minor,
            actor_admin=admin.username,
            note=values.note,
            idempotency_key=idempotency_key,
        )
    except commerce.IdempotencyConflict:
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for another request") from None
    return commerce.admin_account_response(account)


@router.get(
    "/api/commerce/admin/accounts/{account_id}/wallet/transactions",
    response_model=List[WalletTransactionResponse],
)
def admin_wallet_transactions(
    account_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    _get_account_or_404(db, account_id)
    return commerce.list_wallet_transactions(
        db,
        account_id,
        limit=max(1, min(limit, 100)),
    )


@router.post(
    "/api/commerce/admin/accounts/{account_id}/subscription/grant",
    response_model=PortalPurchaseResponse,
)
def admin_grant_plan(
    account_id: int,
    values: AdminGrantPlanRequest,
    bg: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    idempotency_key = _validate_idempotency_key(idempotency_key)
    account = _get_account_or_404(db, account_id)
    plan = _get_plan_or_404(db, values.plan_id)
    try:
        result = commerce.grant_plan(
            db,
            account,
            plan,
            actor_admin=admin.username,
            idempotency_key=idempotency_key,
        )
    except (commerce.PlanConfigurationError, commerce.AccountUnavailable) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except commerce.IdempotencyConflict:
        db.rollback()
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for another request") from None
    _sync_proxy(bg, result)
    return _purchase_response(result)


@router.post(
    "/api/commerce/admin/accounts/{account_id}/subscription/renew",
    response_model=PortalPurchaseResponse,
)
def admin_renew_subscription(
    account_id: int,
    values: AdminRenewSubscriptionRequest,
    bg: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    idempotency_key = _validate_idempotency_key(idempotency_key)
    account = _get_account_or_404(db, account_id)
    try:
        result = commerce.renew_subscription(
            db,
            account,
            days=values.days,
            actor_admin=admin.username,
            idempotency_key=idempotency_key,
        )
    except commerce.SubscriptionUnavailable:
        raise HTTPException(status_code=409, detail="No current subscription") from None
    except commerce.IdempotencyConflict:
        db.rollback()
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for another request") from None
    _sync_proxy(bg, result)
    return _purchase_response(result)


@router.post("/api/commerce/admin/accounts/{account_id}/subscription/disable")
def admin_disable_subscription(
    account_id: int,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    account = _get_account_or_404(db, account_id)
    try:
        user = commerce.disable_subscription(db, account)
    except commerce.SubscriptionUnavailable:
        raise HTTPException(status_code=409, detail="No current subscription") from None
    bg.add_task(xray.operations.remove_user_by_id, user_id=user.id)
    return {"detail": "Subscription disabled"}
