from typing import Generator, Callable, Optional
from fastapi import Depends, Request, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import logging

from app.database.session import SessionLocal
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.services.authorization_service import AuthorizationService
from app.core.security_context import SecurityContext
from app.core.rate_limit import api_limiter

logger = logging.getLogger("app.core.dependencies")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


from app.core.config import settings
from app.core.csrf import validate_csrf


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token_bearer: Optional[str] = Depends(oauth2_scheme_optional),
) -> User:
    """
    P2-1 Authentication Dependency with strict transport precedence:
    1. If auth_token cookie exists:
       - Cookie authentication wins.
       - CSRF protection (double-submit + Origin) applies to mutating requests.
       - Authorization header is ignored (prevents CSRF bypass).
    2. If auth_token cookie does NOT exist:
       - Authorization: Bearer <JWT> authenticates machine/API clients without CSRF.
    3. If neither exists:
       - Raises HTTP 401 Unauthorized.
    """
    auth_service = AuthService(db)

    # 1. Cookie Authentication (Browser Mode)
    auth_cookie = request.cookies.get(settings.AUTH_COOKIE_NAME)

    if auth_cookie:
        # Enforce CSRF token and Origin verification for mutating requests
        validate_csrf(request)
        token = auth_cookie
    elif token_bearer:
        # 2. Machine / API Client Authentication (Bearer Mode)
        token = token_bearer
    else:
        # 3. Unauthenticated
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = auth_service.get_current_user(token)

    # Enforce user-keyed general API rate limiting (100 req/min/user)
    user_key = f"user_{user.id}"
    if api_limiter.is_rate_limited(user_key):
        logger.warning(f"AUDIT | Action: api_rate_limit_exceeded | User: {user.email} | Status: blocked")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 100 requests per minute."
        )

    return user


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token_bearer: Optional[str] = Depends(oauth2_scheme_optional),
) -> Optional[User]:
    auth_cookie = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if auth_cookie:
        token = auth_cookie
    elif token_bearer:
        token = token_bearer
    else:
        return None

    try:
        auth_service = AuthService(db)
        return auth_service.get_current_user(token)
    except Exception:
        return None


def get_security_context(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> SecurityContext:
    """
    Refinement #5: Constructs Request-Scoped SecurityContext object.
    Resolves permissions dynamically via PermissionService.
    """
    perm_svc = PermissionService(db)
    user_perms = perm_svc.get_user_permissions(user.id)

    org_id = user.organization_memberships[0].organization_id if user.organization_memberships else None
    role_ids = [ur.role_id for ur in user.role_assignments]

    return SecurityContext(
        user=user,
        org_id=org_id,
        workspace_id=None,
        role_ids=role_ids,
        permissions=user_perms,
    )


def require_permission(required_permission: str) -> Callable:
    """
    Dependency factory enforcing granular permission authorization.
    Refinement #7: Super Admin bypass.
    Refinement #9: Structured Audit Logging.
    """
    def permission_dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        authz_svc = AuthorizationService(db)
        allowed = authz_svc.check_permission(user, required_permission)
        if not allowed:
            logger.warning(f"AUDIT_RBAC | User: {user.email} | Forbidden: Missing permission {required_permission}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden. Required permission: '{required_permission}'"
            )
        return user

    return permission_dependency