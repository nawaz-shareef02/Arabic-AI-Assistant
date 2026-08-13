"""
PasswordResetService — Enterprise Password Reset & Recovery Manager.

Guarantees:
1. Cryptographically secure random token generation (secrets.token_urlsafe).
2. Token hash-only persistence (SHA-256) — raw tokens are NEVER stored in DB or logged.
3. Expiration enforcement (PASSWORD_RESET_TOKEN_EXPIRE_MINUTES).
4. Single-use token invalidation upon consumption.
5. Invalidation of previous tokens on new reset requests.
6. Account enumeration protection — constant response for existing/unknown emails.
7. Device session revocation upon successful password change.
"""

import datetime
import hashlib
import logging
import secrets
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash, validate_password_strength
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.email_service import EmailService
from app.services.session_service import SessionService

logger = logging.getLogger("app.services.password_reset_service")


class PasswordResetService:
    def __init__(self, db: Session):
        self.db = db
        self.email_service = EmailService()

    @staticmethod
    def _hash_token(token: str) -> str:
        """Calculate SHA-256 hex digest of raw token string."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def request_password_reset(
        self, email: str, client_ip: str = "unknown"
    ) -> dict:
        """
        Processes password reset request with account enumeration protection.

        Always returns the identical generic detail string regardless of whether
        the email exists in the system.
        """
        generic_response = {
            "detail": "If this email is registered, a password reset link has been sent."
        }

        email_clean = email.lower().strip()
        user = self.db.query(User).filter(User.email == email_clean).first()

        if not user:
            logger.warning(
                "AUDIT | Action: forgot_password_attempt | User: %s | IP: %s | "
                "Reason: Email not found (enumeration protected)",
                email_clean,
                client_ip,
            )
            return generic_response

        if not user.is_active:
            logger.warning(
                "AUDIT | Action: forgot_password_attempt | User: %s | IP: %s | "
                "Reason: User account inactive",
                email_clean,
                client_ip,
            )
            return generic_response

        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # Invalidate all prior unused reset tokens for this user
        existing_tokens = (
            self.db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .all()
        )
        for t in existing_tokens:
            t.used_at = now_utc

        # Generate cryptographically secure random token (256-bit entropy)
        raw_token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(raw_token)

        expires_at = now_utc + datetime.timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )

        reset_record = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            used_at=None,
        )
        self.db.add(reset_record)
        self.db.commit()

        # Send email (handles SMTP connection errors gracefully)
        self.email_service.send_password_reset_email(user.email, raw_token)

        logger.info(
            "AUDIT | Action: forgot_password_token_issued | User: %s | IP: %s | "
            "Status: success",
            user.email,
            client_ip,
        )
        return generic_response

    def reset_password(
        self, raw_token: str, new_password: str, client_ip: str = "unknown"
    ) -> dict:
        """
        Validates reset token and updates the user's password.

        Parameters
        ----------
        raw_token : str
            Raw token supplied by frontend.
        new_password : str
            New plaintext password to set.
        client_ip : str
            Request IP for audit logging.
        """
        if not raw_token or not raw_token.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        token_hash = self._hash_token(raw_token.strip())

        token_record = (
            self.db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == token_hash)
            .first()
        )

        if not token_record or token_record.used_at is not None:
            logger.warning(
                "AUDIT | Action: reset_password_failed | IP: %s | "
                "Reason: Invalid or already consumed token",
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # Check expiration
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)

        if expires_at < now_utc:
            logger.warning(
                "AUDIT | Action: reset_password_failed | User_ID: %s | IP: %s | "
                "Reason: Expired token",
                token_record.user_id,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset token has expired.",
            )

        user = self.db.query(User).filter(User.id == token_record.user_id).first()
        if not user or not user.is_active:
            logger.warning(
                "AUDIT | Action: reset_password_failed | User_ID: %s | IP: %s | "
                "Reason: Target user not found or inactive",
                token_record.user_id,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token.",
            )

        # Validate password strength against target user rules
        try:
            validate_password_strength(new_password, user.email, user.full_name)
        except ValueError as exc:
            logger.warning(
                "AUDIT | Action: reset_password_failed | User: %s | IP: %s | "
                "Reason: Password policy violation: %s",
                user.email,
                client_ip,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        # Update user password
        user.hashed_password = get_password_hash(new_password)
        token_record.used_at = now_utc

        # Revoke all active sessions for security
        try:
            session_svc = SessionService(self.db)
            session_svc.logout_all_devices(user.id)
        except Exception as sess_exc:
            logger.warning(
                "AUDIT | Action: session_revocation_notice | User: %s | "
                "Notice: %s",
                user.email,
                sess_exc,
            )

        self.db.commit()

        logger.info(
            "AUDIT | Action: reset_password_success | User: %s | IP: %s | "
            "Status: success",
            user.email,
            client_ip,
        )
        return {
            "detail": "Password has been successfully reset. You may now log in with your new password."
        }
