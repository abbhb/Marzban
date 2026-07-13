"""Authenticated MGMA controls and public short-lived subscription routes."""

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response

from app.db import Session, crud, get_db
from app.dependencies import get_validated_user
from app.models.admin import Admin
from app.models.mgma import MgmaIssueResponse, MgmaSettingsResponse, MgmaSettingsUpdate
from app.models.user import UserResponse
from app.routers.subscription import build_subscription_response
from app.services.mgma import (
    MgmaConfigurationError,
    MgmaTokenRejected,
    MgmaUserIneligible,
    build_public_subscription_url,
    get_real_client_ip,
    get_settings_response,
    issue_token,
    revoke_token,
    update_settings,
    validate_token,
)
from config import XRAY_SUBSCRIPTION_PATH


router = APIRouter(tags=["MGMA"])

NO_STORE_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}


def _not_found() -> HTTPException:
    # Deliberately make malformed, unknown, expired, consumed, and source-denied
    # bearer tokens indistinguishable to unauthenticated callers.
    return HTTPException(
        status_code=404,
        detail="Not Found",
        headers=NO_STORE_HEADERS,
    )


@router.post(
    "/api/user/{username}/mgma",
    response_model=MgmaIssueResponse,
    responses={403: {"description": "Not allowed"}, 404: {"description": "User not found"}},
)
def issue_mgma_url(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    dbuser=Depends(get_validated_user),
):
    """Issue a new temporary URL and immediately invalidate its predecessor."""
    try:
        issued = issue_token(db, dbuser)
    except MgmaUserIneligible:
        raise HTTPException(
            status_code=409,
            detail="Only active or on-hold users can receive a temporary subscription URL",
        ) from None
    except MgmaConfigurationError:
        raise HTTPException(status_code=503, detail="MGMA is not configured") from None

    response.headers.update(NO_STORE_HEADERS)
    return MgmaIssueResponse(
        url=build_public_subscription_url(
            issued.token,
            base_url=str(request.base_url),
        ),
        issued_at=issued.issued_at,
        expires_at=issued.expires_at,
        ttl_seconds=issued.ttl_seconds,
    )


@router.delete("/api/user/{username}/mgma")
def revoke_mgma_url(
    response: Response,
    db: Session = Depends(get_db),
    dbuser=Depends(get_validated_user),
):
    """Revoke the latest temporary URL for one authorized user."""
    revoke_token(db, dbuser)
    response.headers.update(NO_STORE_HEADERS)
    return {"detail": "Temporary subscription URL revoked"}


@router.get("/api/subscription/settings", response_model=MgmaSettingsResponse)
def read_mgma_settings(
    response: Response,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    response.headers.update(NO_STORE_HEADERS)
    return get_settings_response(db)


@router.put("/api/subscription/settings", response_model=MgmaSettingsResponse)
def replace_mgma_settings(
    values: MgmaSettingsUpdate,
    response: Response,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        settings = update_settings(db, values)
    except MgmaConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    response.headers.update(NO_STORE_HEADERS)
    return settings


def _validated_mgma_user(request: Request, token: str, db: Session):
    if "text/html" in request.headers.get("accept", "").lower():
        raise _not_found()
    try:
        return validate_token(db, token, get_real_client_ip(request))
    except MgmaTokenRejected:
        raise _not_found() from None


@router.get(f"/{XRAY_SUBSCRIPTION_PATH}/mgma", include_in_schema=False)
@router.get(f"/{XRAY_SUBSCRIPTION_PATH}/mgma/", include_in_schema=False)
def mgma_subscription(
    request: Request,
    token: str = "",
    user_agent: str = Header(default=""),
    db: Session = Depends(get_db),
):
    dbuser = _validated_mgma_user(request, token, db)
    user = UserResponse.model_validate(dbuser)
    crud.update_user_sub(db, dbuser, user_agent)
    return build_subscription_response(
        user=user,
        user_agent=user_agent,
        ephemeral=True,
    )


@router.get(f"/{XRAY_SUBSCRIPTION_PATH}/mgma/{{client_type}}", include_in_schema=False)
def mgma_subscription_with_client_type(
    request: Request,
    token: str = "",
    client_type: str = Path(
        ...,
        pattern="^(sing-box|clash-meta|clash|outline|v2ray|v2ray-json)$",
    ),
    user_agent: str = Header(default=""),
    db: Session = Depends(get_db),
):
    dbuser = _validated_mgma_user(request, token, db)
    user = UserResponse.model_validate(dbuser)
    crud.update_user_sub(db, dbuser, user_agent)
    return build_subscription_response(
        user=user,
        user_agent=user_agent,
        client_type=client_type,
        ephemeral=True,
    )
