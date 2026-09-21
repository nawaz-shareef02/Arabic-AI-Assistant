"""
Centralized cookie utilities for enterprise authentication transport security (P2-1).

Provides helper functions for setting and clearing HttpOnly authentication cookies
and non-HttpOnly CSRF double-submit cookies with secure enterprise defaults.
"""

import secrets
from typing import Optional
from fastapi import Response
from app.core.config import settings


def generate_csrf_token() -> str:
    """
    Generate a 256-bit cryptographically secure random token (64 hex characters).
    Never derived from user_id, email, timestamp, or any predictable state.
    """
    return secrets.token_hex(32)


def set_auth_cookie(
    response: Response,
    token: str,
    max_age: Optional[int] = None,
) -> None:
    """
    Sets the primary HttpOnly authentication cookie on the response.
    Inaccessible to client-side JavaScript, mitigating token extraction via XSS.
    """
    age = max_age if max_age is not None else (settings.JWT_EXPIRE_MINUTES * 60)
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=age,
        expires=age,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def set_csrf_cookie(
    response: Response,
    csrf_token: str,
    max_age: Optional[int] = None,
) -> None:
    """
    Sets the non-HttpOnly CSRF token cookie on the response.
    Accessible to frontend JavaScript so it can read and attach in the X-CSRF-Token header.
    """
    age = max_age if max_age is not None else (settings.JWT_EXPIRE_MINUTES * 60)
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=age,
        expires=age,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=False,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def clear_auth_cookies(response: Response) -> None:
    """
    Deletes both the auth_token and csrf_token cookies from the response.
    Used during normal logout and session termination.
    """
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
