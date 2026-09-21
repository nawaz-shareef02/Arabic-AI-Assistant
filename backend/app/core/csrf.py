"""
CSRF Protection and Origin Validation (P2-1).

Enforces double-submit CSRF token validation and Origin verification
for cookie-authenticated mutating requests (POST, PUT, PATCH, DELETE).
"""

import hmac
import logging
from typing import Set
from fastapi import Request, HTTPException, status
from app.core.config import settings

logger = logging.getLogger("app.core.csrf")

SAFE_METHODS: Set[str] = {"GET", "HEAD", "OPTIONS", "TRACE"}


def validate_origin(request: Request) -> None:
    """
    Validates the Origin header against settings.ALLOWED_ORIGINS.
    If an Origin header is present and is not authorized, raises HTTP 403 Forbidden.
    If absent, allowed for backward/direct client compatibility per Phase 0 policy.
    """
    origin = request.headers.get("origin")
    if origin:
        normalized_origin = origin.rstrip("/").lower()
        allowed = [o.rstrip("/").lower() for o in settings.ALLOWED_ORIGINS]
        if normalized_origin not in allowed:
            logger.warning(
                f"AUDIT_CSRF | Action: origin_rejected | Origin: {origin} | "
                f"Allowed: {settings.ALLOWED_ORIGINS} | Status: blocked"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Origin '{origin}' is not authorized."
            )


def validate_csrf(request: Request) -> None:
    """
    Enforces double-submit CSRF token comparison and Origin verification
    for cookie-authenticated mutating requests (POST, PUT, PATCH, DELETE).

    Double-submit requirement:
        csrf_token cookie == X-CSRF-Token request header
    """
    # Safe methods do not mutate server state and do not require CSRF tokens
    if request.method.upper() in SAFE_METHODS:
        return

    # 1. Enforce Origin validation if Origin header is present
    validate_origin(request)

    # 2. Extract CSRF token from cookie and request header
    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header_token = (
        request.headers.get("x-csrf-token")
        or request.headers.get("X-CSRF-Token")
    )

    if not cookie_token or not header_token:
        logger.warning(
            f"AUDIT_CSRF | Action: csrf_missing | Method: {request.method} | "
            f"Path: {request.url.path} | CookiePresent: {bool(cookie_token)} | "
            f"HeaderPresent: {bool(header_token)} | Status: blocked"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: CSRF token missing in cookie or request header."
        )

    # 3. Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(cookie_token.strip(), header_token.strip()):
        logger.warning(
            f"AUDIT_CSRF | Action: csrf_mismatch | Method: {request.method} | "
            f"Path: {request.url.path} | Status: blocked"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: CSRF token mismatch."
        )
