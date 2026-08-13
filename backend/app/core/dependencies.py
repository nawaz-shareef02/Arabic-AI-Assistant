from typing import Generator, Callable
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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    auth_service = AuthService(db)
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