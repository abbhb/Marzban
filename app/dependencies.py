from typing import Optional, Tuple, Union
from sqlalchemy import select
from app.models.admin import AdminInDB, AdminValidationResult, Admin
from app.models.user import UserResponse, UserStatus
from app.db import Session, crud, get_db
from config import SUDOERS
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timezone, timedelta
from app.utils.jwt import get_portal_payload, get_subscription_payload
from app.models.mgma import MgmaAccessMode
from app.services.mgma import (
    MgmaTokenRejected,
    get_real_client_ip,
    get_settings,
    source_allowed,
    token_generation_matches,
    validate_token,
)
from app.db.models import PortalAccount, User
from app.services import commerce


portal_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/portal/token",
    auto_error=False,
)


def validate_admin(db: Session, username: str, password: str) -> Optional[AdminValidationResult]:
    """Validate admin credentials with environment variables or database."""
    if SUDOERS.get(username) == password:
        return AdminValidationResult(username=username, is_sudo=True)

    dbadmin = crud.get_admin(db, username)
    if dbadmin and AdminInDB.model_validate(dbadmin).verify_password(password):
        return AdminValidationResult(username=dbadmin.username, is_sudo=dbadmin.is_sudo)

    return None


def get_admin_by_username(username: str, db: Session = Depends(get_db)):
    """Fetch an admin by username from the database."""
    dbadmin = crud.get_admin(db, username)
    if not dbadmin:
        raise HTTPException(status_code=404, detail="Admin not found")
    return dbadmin


def get_dbnode(node_id: int, db: Session = Depends(get_db)):
    """Fetch a node by its ID from the database, raising a 404 error if not found."""
    dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        raise HTTPException(status_code=404, detail="Node not found")
    return dbnode


def validate_dates(start: Optional[Union[str, datetime]], end: Optional[Union[str, datetime]]) -> (datetime, datetime):
    """Validate if start and end dates are correct and if end is after start."""
    try:
        if start:
            start_date = start if isinstance(start, datetime) else datetime.fromisoformat(
                start).astimezone(timezone.utc)
        else:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        if end:
            end_date = end if isinstance(end, datetime) else datetime.fromisoformat(end).astimezone(timezone.utc)
            if start_date and end_date < start_date:
                raise HTTPException(status_code=400, detail="Start date must be before end date")
        else:
            end_date = datetime.now(timezone.utc)

        return start_date, end_date
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date range or format")


def get_user_template(template_id: int, db: Session = Depends(get_db)):
    """Fetch a User Template by its ID, raise 404 if not found."""
    dbuser_template = crud.get_user_template(db, template_id)
    if not dbuser_template:
        raise HTTPException(status_code=404, detail="User Template not found")
    return dbuser_template


def get_current_portal_account(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(portal_oauth2_scheme),
) -> PortalAccount:
    """Authenticate a self-service account without accepting admin JWTs."""

    payload = get_portal_payload(token or "")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate portal credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    account = commerce.get_account(db, payload["account_id"])
    if (
        not account
        or not account.is_active
        or account.username != payload["username"]
        or (
            account.password_reset_at
            and account.password_reset_at > payload["created_at"]
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate portal credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account


MGMA_NO_STORE_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}


def _subscription_not_found(*, no_store: bool = False) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="Not Found",
        headers=MGMA_NO_STORE_HEADERS if no_store else None,
    )


def _resolve_subscription_path(
    db: Session,
    subscription_token: str,
) -> Optional[Tuple[User, str, Optional[datetime]]]:
    """Resolve a subscription path and identify its authentication source."""

    dbuser = (
        db.query(User)
        .filter(User.subscription_token == subscription_token)
        .first()
    )
    if dbuser:
        return dbuser, "stable", None

    sub = get_subscription_payload(subscription_token)
    if not sub:
        return None
    dbuser = crud.get_user(db, sub["username"])
    if not dbuser or dbuser.created_at > sub["created_at"]:
        return None
    # The pre-v0.8.4 custom subscription format encoded ``ceil(time.time())``.
    # Its recorded creation can therefore be almost one second later than the
    # actual issuance.  Include that precision window so a same-second full
    # regeneration cannot leave the old permanent URL authorized.
    if _legacy_path_revoked(dbuser.sub_revoked_at, sub["created_at"]):
        return None
    return dbuser, "legacy", sub["created_at"]


def _legacy_path_revoked(
    revoked_at: Optional[datetime],
    token_created_at: datetime,
) -> bool:
    return bool(
        revoked_at
        and revoked_at + timedelta(seconds=1) > token_created_at
    )


def _capture_subscription_snapshot(
    db: Session,
    request: Request,
    dbuser: User,
    *,
    path_source: str,
    subscription_token: str,
    query_token: Optional[str],
    legacy_created_at: Optional[datetime],
) -> None:
    """Materialize credentials, then reject if their generation changed."""

    snapshot = UserResponse.model_validate(dbuser)
    if query_token is not None:
        stable_path = subscription_token if path_source == "stable" else None
        if not token_generation_matches(
            db,
            dbuser.id,
            query_token,
            subscription_token=stable_path,
        ):
            raise _subscription_not_found(no_store=True)
    else:
        row = db.execute(
            select(User.id, User.sub_revoked_at).where(User.id == dbuser.id)
        ).one_or_none()
        if (
            row is None
            or legacy_created_at is None
            or _legacy_path_revoked(row.sub_revoked_at, legacy_created_at)
        ):
            raise _subscription_not_found(no_store=True)

    request.state.subscription_user_snapshot = snapshot
    request.state.subscription_dbuser = dbuser


def get_validated_sub(
    subscription_token: str,
    request: Request,
    token: Optional[str] = None,
    db: Session = Depends(get_db),
) -> UserResponse:
    settings = get_settings(db)
    has_mgma_query = token is not None
    no_store = has_mgma_query or settings.mode == MgmaAccessMode.ephemeral.value
    source_ip = get_real_client_ip(request)
    if not source_allowed(source_ip, settings):
        raise _subscription_not_found(no_store=no_store)

    resolved_path = _resolve_subscription_path(db, subscription_token)
    if resolved_path is None:
        raise _subscription_not_found(no_store=no_store)
    path_user, path_source, legacy_created_at = resolved_path

    if has_mgma_query:
        # Do this before validating/consuming a single-use bearer, preserving
        # the same opaque browser behavior as the legacy /sub/mgma alias.
        if "text/html" in request.headers.get("accept", "").lower():
            raise _subscription_not_found(no_store=True)
        try:
            dbuser = validate_token(
                db,
                token or "",
                source_ip,
                expected_user_id=path_user.id,
            )
        except MgmaTokenRejected:
            # An explicitly supplied invalid/expired bearer must never fall
            # back to legacy long-lived access in legacy or dual mode.
            raise _subscription_not_found(no_store=True) from None
        _capture_subscription_snapshot(
            db,
            request,
            dbuser,
            path_source=path_source,
            subscription_token=subscription_token,
            query_token=token,
            legacy_created_at=legacy_created_at,
        )
        request.state.mgma_authorized = True
        return dbuser

    # The new stable path is only an opaque user identifier, never an
    # authorization credential. It always requires a valid short-lived MGMA
    # bearer, including while the migration mode is ``legacy`` or ``dual``.
    # Only the old signed subscription token keeps its historical no-query
    # behavior during the compatibility window.
    if (
        path_source == "stable"
        or settings.mode == MgmaAccessMode.ephemeral.value
    ):
        raise _subscription_not_found(no_store=True)

    _capture_subscription_snapshot(
        db,
        request,
        path_user,
        path_source=path_source,
        subscription_token=subscription_token,
        query_token=None,
        legacy_created_at=legacy_created_at,
    )
    request.state.mgma_authorized = False
    return path_user


def get_validated_user(
        username: str,
        admin: Admin = Depends(Admin.get_current),
        db: Session = Depends(get_db)
) -> UserResponse:
    dbuser = crud.get_user(db, username)
    if not dbuser:
        raise HTTPException(status_code=404, detail="User not found")

    if not (admin.is_sudo or (dbuser.admin and dbuser.admin.username == admin.username)):
        raise HTTPException(status_code=403, detail="You're not allowed")

    return dbuser


def get_expired_users_list(db: Session, admin: Admin, expired_after: Optional[datetime] = None,
                           expired_before: Optional[datetime] = None):
    expired_before = expired_before or datetime.now(timezone.utc)
    expired_after = expired_after or datetime.min.replace(tzinfo=timezone.utc)

    dbadmin = crud.get_admin(db, admin.username)
    dbusers = crud.get_users(
        db=db,
        status=[UserStatus.expired, UserStatus.limited],
        admin=dbadmin if not admin.is_sudo else None
    )

    return [
        u for u in dbusers
        if u.expire and expired_after.timestamp() <= u.expire <= expired_before.timestamp()
    ]
