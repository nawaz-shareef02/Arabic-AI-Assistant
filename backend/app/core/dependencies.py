from typing import Generator
from fastapi import Depends, Request, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.user import User
from app.services.auth_service import AuthService
from app.core.rate_limit import api_limiter
import logging

logger = logging.getLogger("app.core.dependencies")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

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