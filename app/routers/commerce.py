"""Self-service portal and sudo-only commerce administration APIs."""

from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app import xray
from app.db import Session, get_db
from app.db.models import (
    ExternalSubscriptionNode,
    ExternalSubscriptionSource,
    PortalAccount,
    SubscriptionPlan,
)
from app.dependencies import get_current_portal_account
from app.models.admin import Admin
from app.models.commerce import (
    AdminGrantPlanRequest,
    AdminManagedAccountCreateRequest,
    AdminManagedAccountCreateResponse,
    AdminRenewSubscriptionRequest,
    ExternalSubscriptionCredentialUpdate,
    ExternalSubscriptionNodeResponse,
    ExternalSubscriptionSourceCreate,
    ExternalSubscriptionSourceResponse,
    ExternalSubscriptionSourceUpdate,
    IPBlockListSource,
    IPBlockListStatus,
    IPBlockCreate,
    IPBlockResponse,
    InvitationListStatus,
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationResponse,
    GeneratedPasswordResponse,
    PaginatedResponse,
    PortalAccountListStatus,
    PortalAccountAdminResponse,
    PortalAccountResponse,
    PortalMeResponse,
    PortalPasswordChangeRequest,
    PortalPurchaseRequest,
    PortalPurchaseResponse,
    PortalRegister,
    PortalToken,
    PortalSecuritySettingsResponse,
    PortalSecuritySettingsUpdate,
    SubscriptionPlanCreate,
    SubscriptionPlanAdminResponse,
    SubscriptionPlanResponse,
    SubscriptionPlanUpdate,
    WalletRechargeRequest,
    WalletTransactionResponse,
)
from app.models.mgma import MgmaIssueResponse
from app.models.user import UserStatus
from app.services import commerce, external_subscriptions, portal_security
from app.services.mgma import (
    MgmaConfigurationError,
    MgmaUserIneligible,
    build_public_subscription_url,
    issue_token,
    regenerate_subscription,
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


@router.get("/api/commerce/admin/group-catalog")
def admin_group_catalog(admin: Admin = Depends(Admin.check_sudo_admin)):
    from app.services.plan_groups import group_catalog
    return {"groups": group_catalog(), "external_group": "MGMA · External"}


def _get_plan_or_404(db: Session, plan_id: int) -> SubscriptionPlan:
    plan = commerce.get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    return plan


def _get_external_source_or_404(
    db: Session,
    source_id: int,
) -> ExternalSubscriptionSource:
    source = db.get(ExternalSubscriptionSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="External subscription not found")
    return source


def _external_error(exc: external_subscriptions.ExternalSubscriptionError) -> HTTPException:
    if exc.code in {
        "encryption_key_unavailable",
        "encrypted_data_unavailable",
        "internal_error",
        "overlay_limit_exceeded",
    }:
        return HTTPException(status_code=503, detail=exc.code)
    if exc.code == "source_not_found":
        return HTTPException(status_code=404, detail=exc.code)
    if exc.code in {
        "credential_not_configured",
        "refresh_in_progress",
        "source_disabled",
    }:
        return HTTPException(status_code=409, detail=exc.code)
    return HTTPException(status_code=422, detail=exc.code)


def _refresh_external_source_for_admin(
    db: Session,
    source_id: int,
) -> ExternalSubscriptionSource:
    try:
        return external_subscriptions.refresh_source(db, source_id)
    except external_subscriptions.ExternalSubscriptionConfigurationError as exc:
        raise _external_error(exc) from None
    except (
        external_subscriptions.ExternalSubscriptionFetchError,
        external_subscriptions.ExternalSubscriptionParseError,
    ):
        # Refresh metadata and the last-known-good node set were committed by
        # the service. Return only the stable status code projection.
        return _get_external_source_or_404(db, source_id)


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


@router.post("/api/portal/password/change", status_code=status.HTTP_204_NO_CONTENT)
def portal_change_password(
    request: Request,
    response: Response,
    values: PortalPasswordChangeRequest,
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    client_key = _client_key(request)
    rate_key = f"portal-password-change:{client_key}:{account.id}"
    _rate_limit(rate_key, limit=5, window_seconds=300)
    try:
        commerce.change_account_password(
            db,
            account,
            current_password=values.current_password,
            new_password=values.new_password,
        )
    except commerce.IncorrectPassword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        ) from None
    PORTAL_RATE_LIMITER.reset(rate_key)
    response.headers.update(NO_STORE_HEADERS)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE_HEADERS)


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
        url=build_public_subscription_url(
            account.proxy_user.subscription_token,
            issued.token,
            base_url=str(request.base_url),
        ),
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


@router.post(
    "/api/portal/subscription/regenerate",
    response_model=MgmaIssueResponse,
)
def portal_regenerate_subscription(
    request: Request,
    response: Response,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    """Rotate the complete subscription, then authorize its new stable URL.

    Unlike a normal MGMA refresh, this destructive operation changes the
    stable path and all proxy credentials.  Existing subscription URLs and
    imported node credentials stop working immediately.
    """

    dbuser = account.proxy_user
    if not dbuser:
        raise HTTPException(status_code=409, detail="No active subscription")
    try:
        issued = regenerate_subscription(db, dbuser)
    except MgmaUserIneligible:
        raise HTTPException(status_code=409, detail="Subscription is not active") from None
    except MgmaConfigurationError:
        raise HTTPException(status_code=503, detail="MGMA is not configured") from None

    if dbuser.status in (UserStatus.active, UserStatus.on_hold):
        bg.add_task(xray.operations.update_user_by_id, user_id=dbuser.id)
    response.headers.update(NO_STORE_HEADERS)
    return MgmaIssueResponse(
        url=build_public_subscription_url(
            dbuser.subscription_token,
            issued.token,
            base_url=str(request.base_url),
        ),
        issued_at=issued.issued_at,
        expires_at=issued.expires_at,
        ttl_seconds=issued.ttl_seconds,
    )


@router.get(
    "/api/commerce/admin/plans",
    response_model=List[SubscriptionPlanAdminResponse],
)
def admin_list_plans(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return commerce.list_plans(db)


@router.post(
    "/api/commerce/admin/plans",
    response_model=SubscriptionPlanAdminResponse,
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
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plan name already exists") from None


@router.get("/api/commerce/admin/local-node-catalog")
def admin_local_node_catalog(_admin: Admin = Depends(Admin.check_sudo_admin)):
    from app.services.local_nodes import node_catalog
    return node_catalog()


@router.put(
    "/api/commerce/admin/plans/{plan_id}",
    response_model=SubscriptionPlanAdminResponse,
)
def admin_update_plan(
    plan_id: int,
    values: SubscriptionPlanUpdate,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    plan = _get_plan_or_404(db, plan_id)
    try:
        updated = commerce.update_plan(db, plan, values)
        if "inbound_tags" in values.model_fields_set:
            for user_id, user_status in commerce.plan_managed_user_states(
                db, updated.id
            ):
                operation = (
                    xray.operations.update_user_by_id
                    if user_status in (UserStatus.active, UserStatus.on_hold)
                    else xray.operations.remove_user_by_id
                )
                bg.add_task(operation, user_id=user_id)
        return updated
    except commerce.PlanConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plan name already exists") from None


@router.get(
    "/api/commerce/admin/external-subscriptions",
    response_model=List[ExternalSubscriptionSourceResponse],
)
def admin_list_external_subscriptions(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return (
        db.query(ExternalSubscriptionSource)
        .options(joinedload(ExternalSubscriptionSource.owner))
        .order_by(ExternalSubscriptionSource.id.desc())
        .all()
    )


@router.post(
    "/api/commerce/admin/external-subscriptions",
    response_model=ExternalSubscriptionSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_external_subscription(
    values: ExternalSubscriptionSourceCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    credential = values.url.get_secret_value() if values.url else None
    try:
        source = external_subscriptions.create_source(
            db,
            name=values.name,
            group_name=values.group_name or values.name,
            created_by=admin.username,
            enabled=values.enabled,
            refresh_interval_minutes=values.refresh_interval_minutes,
            url=credential,
        )
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="External subscription name or group already exists",
        ) from None
    if credential and source.enabled:
        return _refresh_external_source_for_admin(db, source.id)
    return source


@router.put(
    "/api/commerce/admin/external-subscriptions/{source_id}",
    response_model=ExternalSubscriptionSourceResponse,
)
def admin_update_external_subscription(
    source_id: int,
    values: ExternalSubscriptionSourceUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    source = _get_external_source_or_404(db, source_id)
    try:
        return external_subscriptions.update_source(
            db,
            source,
            name=values.name,
            enabled=values.enabled,
            refresh_interval_minutes=values.refresh_interval_minutes,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="External subscription name already exists",
        ) from None


@router.post(
    "/api/commerce/admin/external-subscriptions/{source_id}/credential",
    response_model=ExternalSubscriptionSourceResponse,
)
def admin_replace_external_subscription_credential(
    source_id: int,
    values: ExternalSubscriptionCredentialUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    source = _get_external_source_or_404(db, source_id)
    try:
        source = external_subscriptions.replace_source_url(
            db,
            source,
            values.url.get_secret_value(),
        )
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None
    if source.enabled:
        return _refresh_external_source_for_admin(db, source.id)
    return source


@router.delete(
    "/api/commerce/admin/external-subscriptions/{source_id}/credential",
    response_model=ExternalSubscriptionSourceResponse,
)
def admin_delete_external_subscription_credential(
    source_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    source = _get_external_source_or_404(db, source_id)
    try:
        return external_subscriptions.replace_source_url(db, source, None)
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None


@router.post(
    "/api/commerce/admin/external-subscriptions/{source_id}/refresh",
    response_model=ExternalSubscriptionSourceResponse,
)
def admin_refresh_external_subscription(
    source_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    _get_external_source_or_404(db, source_id)
    return _refresh_external_source_for_admin(db, source_id)


@router.post(
    "/api/commerce/admin/external-subscriptions/{source_id}/snapshot",
    response_model=ExternalSubscriptionSourceResponse,
)
async def admin_import_external_subscription_snapshot(
    source_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    source = _get_external_source_or_404(db, source_id)
    content = await file.read(external_subscriptions.MAX_SOURCE_BYTES + 1)
    try:
        return external_subscriptions.import_snapshot(db, source, content)
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None


def _parse_node_ids_filter(value: Optional[str]) -> Optional[list[int]]:
    if value is None:
        return None
    try:
        node_ids = [int(item) for item in value.split(",") if item]
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid node IDs") from None
    if (
        not node_ids
        or len(node_ids) > 1000
        or any(node_id <= 0 for node_id in node_ids)
        or len(set(node_ids)) != len(node_ids)
    ):
        raise HTTPException(status_code=422, detail="Invalid node IDs")
    return node_ids


@router.get(
    "/api/commerce/admin/external-subscriptions/{source_id}/nodes",
    response_model=PaginatedResponse[ExternalSubscriptionNodeResponse],
)
def admin_list_external_subscription_nodes(
    source_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=256),
    active: Optional[bool] = Query(default=None),
    ids: Optional[str] = Query(default=None, max_length=12_000),
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    _get_external_source_or_404(db, source_id)
    node_ids = _parse_node_ids_filter(ids)
    query = db.query(ExternalSubscriptionNode).filter(
        ExternalSubscriptionNode.source_id == source_id
    )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ExternalSubscriptionNode.name.ilike(pattern),
                ExternalSubscriptionNode.proxy_type.ilike(pattern),
            )
        )
    if active is not None:
        query = query.filter(ExternalSubscriptionNode.is_active.is_(active))
    if node_ids is not None:
        query = query.filter(ExternalSubscriptionNode.id.in_(node_ids))
    total = query.count()
    items = (
        query.order_by(
            ExternalSubscriptionNode.position.asc(),
            ExternalSubscriptionNode.id.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse[ExternalSubscriptionNodeResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/api/commerce/admin/external-subscriptions/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def admin_delete_external_subscription(
    source_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        source = external_subscriptions.lock_external_sources_for_update(
            db,
            [source_id],
        )[source_id]
    except external_subscriptions.ExternalSubscriptionError as exc:
        raise _external_error(exc) from None
    if source.plan_selections:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="source_in_use",
        )
    try:
        db.delete(source)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="source_in_use") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_owned_external_source(db: Session, source_id: int, account: PortalAccount):
    source = db.query(ExternalSubscriptionSource).filter_by(
        id=source_id, owner_account_id=account.id
    ).first()
    if source is None:
        raise HTTPException(status_code=404, detail="External subscription not found")
    return source


def _private_external_rate_limit(account: PortalAccount) -> None:
    _rate_limit(f"portal-external:{account.id}", limit=20, window_seconds=600)


@router.get("/api/portal/external-subscriptions", response_model=List[ExternalSubscriptionSourceResponse])
def portal_list_external_subscriptions(
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    return db.query(ExternalSubscriptionSource).filter_by(owner_account_id=account.id).order_by(
        ExternalSubscriptionSource.id.desc()
    ).all()


@router.post("/api/portal/external-subscriptions", response_model=ExternalSubscriptionSourceResponse, status_code=201)
def portal_create_external_subscription(
    values: ExternalSubscriptionSourceCreate,
    db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    _private_external_rate_limit(account)
    credential = values.url.get_secret_value() if values.url else None
    try:
        source = external_subscriptions.create_source(
            db, name=values.name, group_name=values.group_name or values.name,
            created_by=account.username, owner_account_id=account.id,
            enabled=values.enabled, refresh_interval_minutes=values.refresh_interval_minutes,
            url=credential,
        )
    except external_subscriptions.ExternalSubscriptionError as exc:
        db.rollback()
        raise _external_error(exc) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="External subscription name or group already exists") from None
    return _refresh_external_source_for_admin(db, source.id) if credential and source.enabled else source


# Share the established CRUD/refresh implementation after an ownership check.
# Portal clients never supply an owner, and cannot transfer or share a source.
@router.put("/api/portal/external-subscriptions/{source_id}", response_model=ExternalSubscriptionSourceResponse)
def portal_update_external_subscription(
    source_id: int, values: ExternalSubscriptionSourceUpdate,
    db: Session = Depends(get_db), account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    return admin_update_external_subscription(source_id, values, db, account)


@router.post("/api/portal/external-subscriptions/{source_id}/credential", response_model=ExternalSubscriptionSourceResponse)
def portal_replace_external_subscription_credential(
    source_id: int, values: ExternalSubscriptionCredentialUpdate,
    db: Session = Depends(get_db), account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    _private_external_rate_limit(account)
    return admin_replace_external_subscription_credential(source_id, values, db, account)


@router.delete("/api/portal/external-subscriptions/{source_id}/credential", response_model=ExternalSubscriptionSourceResponse)
def portal_delete_external_subscription_credential(
    source_id: int, db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    return admin_delete_external_subscription_credential(source_id, db, account)


@router.post("/api/portal/external-subscriptions/{source_id}/refresh", response_model=ExternalSubscriptionSourceResponse)
def portal_refresh_external_subscription(
    source_id: int, db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    _private_external_rate_limit(account)
    return _refresh_external_source_for_admin(db, source_id)


@router.post("/api/portal/external-subscriptions/{source_id}/snapshot", response_model=ExternalSubscriptionSourceResponse)
async def portal_import_external_subscription_snapshot(
    source_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    _private_external_rate_limit(account)
    return await admin_import_external_subscription_snapshot(source_id, file, db, account)


@router.get("/api/portal/external-subscriptions/{source_id}/nodes", response_model=PaginatedResponse[ExternalSubscriptionNodeResponse])
def portal_list_external_subscription_nodes(
    source_id: int, page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=256),
    active: Optional[bool] = Query(default=None),
    ids: Optional[str] = Query(default=None, max_length=12_000),
    db: Session = Depends(get_db), account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    return admin_list_external_subscription_nodes(source_id, page, page_size, search, active, ids, db, account)


@router.delete("/api/portal/external-subscriptions/{source_id}", status_code=204)
def portal_delete_external_subscription(
    source_id: int, db: Session = Depends(get_db),
    account: PortalAccount = Depends(get_current_portal_account),
):
    _get_owned_external_source(db, source_id, account)
    return admin_delete_external_subscription(source_id, db, account)


@router.get(
    "/api/commerce/admin/invitations",
    response_model=PaginatedResponse[InvitationResponse],
)
def admin_list_invitations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=500),
    status_filter: Optional[InvitationListStatus] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    items, total = portal_security.list_invitations(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )
    return PaginatedResponse[InvitationResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


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
    response_model=PaginatedResponse[IPBlockResponse],
)
def admin_list_ip_blocks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=500),
    status_filter: Optional[IPBlockListStatus] = Query(default=None, alias="status"),
    source: Optional[IPBlockListSource] = Query(default=None),
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    items, total = portal_security.list_blocks(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        source=source,
    )
    return PaginatedResponse[IPBlockResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


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
    response_model=PaginatedResponse[PortalAccountAdminResponse],
)
def admin_list_accounts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=128),
    status_filter: Optional[PortalAccountListStatus] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    accounts, total = commerce.list_accounts(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )
    return PaginatedResponse[PortalAccountAdminResponse](
        items=[commerce.admin_account_response(account) for account in accounts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/api/commerce/admin/accounts",
    response_model=AdminManagedAccountCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_managed_account(
    values: AdminManagedAccountCreateRequest,
    bg: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    plan = _get_plan_or_404(db, values.plan_id)
    try:
        result = commerce.create_managed_account(
            db,
            username=values.username,
            plan=plan,
            actor_admin=admin.username,
        )
    except commerce.AccountExists:
        raise HTTPException(status_code=409, detail="Username is unavailable") from None
    except (commerce.PlanConfigurationError, commerce.AccountUnavailable) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    _sync_proxy(bg, result.application)
    response.headers.update(NO_STORE_HEADERS)
    return AdminManagedAccountCreateResponse(
        username=result.application.account.username,
        password=result.password,
        account=commerce.admin_account_response(result.application.account),
    )


@router.get(
    "/api/commerce/admin/accounts/{account_id}",
    response_model=PortalAccountAdminResponse,
)
def admin_get_account(
    account_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    return commerce.admin_account_response(_get_account_or_404(db, account_id))


@router.post(
    "/api/commerce/admin/accounts/{account_id}/password/reset",
    response_model=GeneratedPasswordResponse,
)
def admin_reset_account_password(
    account_id: int,
    response: Response,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    account = _get_account_or_404(db, account_id)
    password = commerce.reset_account_password(db, account)
    response.headers.update(NO_STORE_HEADERS)
    return GeneratedPasswordResponse(username=account.username, password=password)


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
