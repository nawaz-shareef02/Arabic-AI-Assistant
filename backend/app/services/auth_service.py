import datetime
from jose import jwt, JWTError
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.core.security import verify_password, get_password_hash, create_access_token, validate_password_strength
from app.core.config import settings
import logging

logger = logging.getLogger("app.services.auth_service")

class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register_user(self, request: RegisterRequest, client_ip: str = "unknown") -> User:
        existing_user = self.db.query(User).filter(User.email == request.email).first()
        if existing_user:
            logger.warning(f"AUDIT | Action: register_failed | User: {request.email} | IP: {client_ip} | Reason: Email already exists")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists."
            )
        
        try:
            validate_password_strength(request.password, request.email, request.full_name)
        except ValueError as e:
            logger.warning(f"AUDIT | Action: register_failed | User: {request.email} | IP: {client_ip} | Reason: Password strength check failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        
        hashed_pw = get_password_hash(request.password)
        new_user = User(
            email=request.email,
            hashed_password=hashed_pw,
            full_name=request.full_name,
            organization=request.organization,
            preferred_language=request.preferred_language or "en",
            role="employee",
            is_active=True
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        logger.info(f"AUDIT | Action: register_success | User: {request.email} | IP: {client_ip} | Status: success")
        return new_user

    def authenticate_user(self, request: LoginRequest, client_ip: str = "unknown") -> User:
        user = self.db.query(User).filter(User.email == request.email).first()
        if not user:
            logger.warning(f"AUDIT | Action: login_failed | User: {request.email} | IP: {client_ip} | Reason: Non-existent user")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not verify_password(request.password, user.hashed_password):
            logger.warning(f"AUDIT | Action: login_failed | User: {request.email} | IP: {client_ip} | Reason: Invalid password")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            logger.warning(f"AUDIT | Action: login_failed | User: {request.email} | IP: {client_ip} | Reason: Inactive user")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User account is inactive"
            )
        
        user.last_login = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        logger.info(f"AUDIT | Action: login_success | User: {user.email} | IP: {client_ip} | Status: success")
        return user

    def generate_token(self, user: User) -> TokenResponse:
        access_token = create_access_token(subject=user.email)
        return TokenResponse(
            access_token=access_token,
            token_type="bearer"
        )

    def get_current_user(self, token: str) -> User:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            email: str = payload.get("sub")
            if email is None:
                logger.warning("AUDIT | Action: jwt_invalid | Reason: Missing sub claim | Status: failure")
                raise credentials_exception
        except jwt.ExpiredSignatureError:
            logger.warning("AUDIT | Action: jwt_expired | Status: failure")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except JWTError as e:
            logger.warning(f"AUDIT | Action: jwt_invalid | Reason: {str(e)} | Status: failure")
            raise credentials_exception
        
        user = self.db.query(User).filter(User.email == email).first()
        if user is None:
            logger.warning(f"AUDIT | Action: unauthorized_access | User: {email} | Reason: User not found in DB")
            raise credentials_exception
        if not user.is_active:
            logger.warning(f"AUDIT | Action: unauthorized_access | User: {email} | Reason: Inactive user account")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
        return user
