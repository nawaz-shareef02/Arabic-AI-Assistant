import logging
from pydantic import BaseModel
from fastapi import APIRouter, Depends, status, Request, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.services.auth_service import AuthService
from app.services.session_service import SessionService
from app.services.password_reset_service import PasswordResetService
from app.core.rate_limit import (
    login_limiter,
    register_limiter,
    forgot_password_limiter,
    reset_password_limiter,
    AccountLockoutLimiter,
)

logger = logging.getLogger("app.api.v1.auth")
router = APIRouter(prefix="/auth", tags=["AUTH"])


class RefreshTokenRequest(BaseModel):
    refresh_token: str


def get_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, fastapi_req: Request, db: Session = Depends(get_db)):
    client_ip = get_client_ip(fastapi_req)
    if register_limiter.is_rate_limited(client_ip):
        logger.warning(f"AUDIT | Action: rate_limit_exceeded | Key: {client_ip} | Limiter: register | Status: blocked")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(register_limiter.get_retry_after(client_ip))},
            detail="Too many registration attempts. Please try again in an hour."
        )
    auth_service = AuthService(db)
    return auth_service.register_user(request, client_ip)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login(request: LoginRequest, fastapi_req: Request, db: Session = Depends(get_db)):
    client_ip = get_client_ip(fastapi_req)

    # Brute-force account lockout check
    if AccountLockoutLimiter.is_locked_out(request.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to multiple failed login attempts. Please try again in 15 minutes."
        )

    if login_limiter.is_rate_limited(client_ip):
        logger.warning(f"AUDIT | Action: rate_limit_exceeded | Key: {client_ip} | Limiter: login | Status: blocked")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(login_limiter.get_retry_after(client_ip))},
            detail="Too many login attempts. Please try again in 15 minutes."
        )

    auth_service = AuthService(db)
    try:
        user = auth_service.authenticate_user(request, client_ip)
        AccountLockoutLimiter.reset_failed_attempts(request.email)
        return auth_service.generate_token(user)
    except HTTPException as e:
        if e.status_code == 401:
            AccountLockoutLimiter.record_failed_attempt(request.email)
        raise e


@router.post("/token", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login_for_access_token(
    fastapi_req: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    client_ip = get_client_ip(fastapi_req)

    if AccountLockoutLimiter.is_locked_out(form_data.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to multiple failed login attempts. Please try again in 15 minutes."
        )

    if login_limiter.is_rate_limited(client_ip):
        logger.warning(f"AUDIT | Action: rate_limit_exceeded | Key: {client_ip} | Limiter: login_token | Status: blocked")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(login_limiter.get_retry_after(client_ip))},
            detail="Too many login attempts. Please try again in 15 minutes."
        )

    auth_service = AuthService(db)
    login_req = LoginRequest(email=form_data.username, password=form_data.password)
    try:
        user = auth_service.authenticate_user(login_req, client_ip)
        AccountLockoutLimiter.reset_failed_attempts(form_data.username)
        return auth_service.generate_token(user)
    except HTTPException as e:
        if e.status_code == 401:
            AccountLockoutLimiter.record_failed_attempt(form_data.username)
        raise e


@router.post("/refresh", summary="Refresh Token Rotation")
def refresh_token(
    req: RefreshTokenRequest,
    fastapi_req: Request,
    db: Session = Depends(get_db)
):
    """Refinement #9: Refresh Token Rotation & Family Replay Protection."""
    client_ip = get_client_ip(fastapi_req)
    ua = fastapi_req.headers.get("user-agent", "")
    sess_svc = SessionService(db)
    return sess_svc.rotate_refresh_token(req.refresh_token, user_agent=ua, client_ip=client_ip)


@router.post("/logout-all", summary="Logout All Devices")
def logout_all_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sess_svc = SessionService(db)
    sess_svc.logout_all_devices(current_user.id)
    return {"message": "Successfully logged out from all active device sessions."}


@router.get("/sessions", summary="List Active Device Sessions")
def list_active_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Refinement #2: List Active Device Sessions with Fingerprint Data."""
    sess_svc = SessionService(db)
    return sess_svc.get_user_active_sessions(current_user.id)


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(
    request: ForgotPasswordRequest,
    fastapi_req: Request,
    db: Session = Depends(get_db),
):
    """
    Request password reset email.
    Enumeration-protected: returns identical success response regardless of email existence.
    """
    client_ip = get_client_ip(fastapi_req)
    if forgot_password_limiter.is_rate_limited(client_ip):
        logger.warning(
            f"AUDIT | Action: rate_limit_exceeded | Key: {client_ip} | "
            f"Limiter: forgot_password | Status: blocked"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(forgot_password_limiter.get_retry_after(client_ip))},
            detail="Too many password reset requests. Please try again in an hour.",
        )

    reset_svc = PasswordResetService(db)
    return reset_svc.request_password_reset(request.email, client_ip)


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(
    request: ResetPasswordRequest,
    fastapi_req: Request,
    db: Session = Depends(get_db),
):
    """
    Reset user password using token from email.
    Validates token single-use status, expiration, and updates password.
    """
    client_ip = get_client_ip(fastapi_req)
    if reset_password_limiter.is_rate_limited(client_ip):
        logger.warning(
            f"AUDIT | Action: rate_limit_exceeded | Key: {client_ip} | "
            f"Limiter: reset_password | Status: blocked"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(reset_password_limiter.get_retry_after(client_ip))},
            detail="Too many password reset attempts. Please try again in 15 minutes.",
        )

    reset_svc = PasswordResetService(db)
    return reset_svc.reset_password(request.token, request.new_password, client_ip)


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user