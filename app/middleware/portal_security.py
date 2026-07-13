"""Pre-routing IP deny and authentication-failure accounting."""

from __future__ import annotations

from math import ceil

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.db import GetDB
from app.services import portal_security
from app.services.mgma import get_real_client_ip
from config import XRAY_SUBSCRIPTION_PATH


AUTH_FAILURE_STATUS = {
    status.HTTP_400_BAD_REQUEST,
    status.HTTP_401_UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN,
    status.HTTP_409_CONFLICT,
    status.HTTP_422_UNPROCESSABLE_ENTITY,
    status.HTTP_429_TOO_MANY_REQUESTS,
}


def tracked_failure_kind(path: str) -> str | None:
    if path == "/api/portal/register":
        return portal_security.REGISTRATION_KIND
    if path == "/api/portal/token":
        return "portal_login"
    if path == "/api/admin/token":
        return "admin_login"
    return None


def blacklist_enforced(path: str) -> bool:
    """Protect public credentials while retaining sudo recovery APIs."""

    return (
        path.startswith("/api/portal")
        or path == "/api/admin/token"
        or path.startswith(f"/{XRAY_SUBSCRIPTION_PATH}/")
    )


def blocked_response(*, expires_at=None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if expires_at is not None:
        remaining = max(1, ceil((expires_at - portal_security.utc_now()).total_seconds()))
        headers["Retry-After"] = str(remaining)
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": "portal.accessDenied"},
        headers=headers,
    )


class PortalSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path.rstrip("/") or "/"
        kind = tracked_failure_kind(path)
        enforced = blacklist_enforced(path)
        if not enforced and kind is None:
            return await call_next(request)

        source_ip = get_real_client_ip(request)
        if not source_ip:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "A valid client IP is required"},
                headers={"Cache-Control": "no-store"},
            )

        with GetDB() as db:
            block = portal_security.find_active_block(db, source_ip)
            if block:
                return blocked_response(expires_at=block.expires_at)

        response = await call_next(request)
        if kind:
            with GetDB() as db:
                if response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED):
                    portal_security.reset_failures(db, source_ip=source_ip, kind=kind)
                elif response.status_code in AUTH_FAILURE_STATUS:
                    portal_security.record_failure(db, source_ip=source_ip, kind=kind)
        return response
