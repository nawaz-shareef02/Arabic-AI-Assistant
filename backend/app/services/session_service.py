"""
SessionService — Refinements #1, #2, #4 & #9:
Device Fingerprinting, SHA-256 Refresh Token Rotation & Token Family Protection.
"""

import uuid
import hashlib
import datetime
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.session_repository import SessionRepository
from app.core.security_metrics import security_metrics
from app.services.audit_event_publisher import AuditEventPublisher

logger = logging.getLogger("app.services.session_service")


class SessionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SessionRepository(db)
        self.publisher = AuditEventPublisher(db)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Refinement #1: SHA-256 Token Hashing."""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    def parse_user_agent(user_agent_str: str) -> Dict[str, str]:
        """Refinement #2: Parses browser, OS, and device_type from User-Agent."""
        ua = (user_agent_str or "").lower()
        browser = "Chrome" if "chrome" in ua else "Firefox" if "firefox" in ua else "Safari" if "safari" in ua else "Unknown"
        os = "Windows" if "windows" in ua else "Mac" if "macintosh" in ua else "Linux" if "linux" in ua else "iOS" if "iphone" in ua else "Android" if "android" in ua else "Unknown"
        device_type = "mobile" if ("iphone" in ua or "android" in ua) else "tablet" if "ipad" in ua else "desktop"
        return {"browser": browser, "os": os, "device_type": device_type}

    def create_user_session(
        self,
        user: User,
        user_agent: str = "",
        client_ip: str = "127.0.0.1",
        family_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raw_refresh_token = str(uuid.uuid4())
        token_hash = self.hash_token(raw_refresh_token)
        family = family_id or str(uuid.uuid4())
        device_info = self.parse_user_agent(user_agent)
        device_id = self.hash_token(f"{user.id}:{device_info['browser']}:{device_info['os']}:{client_ip}")[:32]

        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)

        sess = self.repo.create_session(
            user_id=user.id,
            family_id=family,
            refresh_token_hash=token_hash,
            device_id=device_id,
            device_name=f"{device_info['browser']} on {device_info['os']}",
            device_type=device_info["device_type"],
            browser=device_info["browser"],
            os=device_info["os"],
            client_ip=client_ip,
            risk_score=0.0,
            expires_at=expires_at,
        )

        return {
            "session_uuid": str(sess.uuid),
            "refresh_token": raw_refresh_token,
            "family_id": family,
            "expires_at": expires_at.isoformat(),
        }

    def rotate_refresh_token(self, raw_refresh_token: str, user_agent: str = "", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
        """Refinement #9: Refresh token rotation & Token Family replay detection."""
        token_hash = self.hash_token(raw_refresh_token)

        # Replay attack check
        if self.repo.is_token_blacklisted(token_hash):
            sess = self.repo.get_by_refresh_hash(token_hash)
            if sess:
                # Invalidate entire token family!
                self.repo.invalidate_token_family(sess.family_id)
                security_metrics.increment("token_revocations")
                self.publisher.publish_event(
                    action="JWT Replay Detected",
                    resource_type="Security",
                    category="Security",
                    user_id=sess.user_id,
                    status="failure",
                    metadata_json={"family_id": sess.family_id, "severity": "HIGH"},
                )
            raise HTTPException(status_code=401, detail="Compromised refresh token detected. Session terminated.")

        sess = self.repo.get_by_refresh_hash(token_hash)
        if not sess or not sess.is_active:
            raise HTTPException(status_code=401, detail="Invalid or expired session token.")

        now = datetime.datetime.now(datetime.timezone.utc)
        if sess.expires_at < now:
            sess.is_active = False
            self.db.commit()
            raise HTTPException(status_code=401, detail="Session expired.")

        # Invalidate old refresh token
        sess.is_active = False
        self.repo.blacklist_token(token_hash)

        # Issue new token in same family
        new_session_data = self.create_user_session(
            user=sess.user,
            user_agent=user_agent,
            client_ip=client_ip,
            family_id=sess.family_id,
        )

        from app.core.security import create_access_token
        access_token = create_access_token({
            "sub": sess.user.email,
            "user_id": sess.user.id,
            "org_id": sess.user.organization_memberships[0].organization_id if sess.user.organization_memberships else None,
            "role_ids": [r.role_id for r in sess.user.role_assignments],
        })

        return {
            "access_token": access_token,
            "refresh_token": new_session_data["refresh_token"],
            "token_type": "bearer",
        }

    def logout_all_devices(self, user_id: int) -> None:
        self.repo.invalidate_all_user_sessions(user_id)
        security_metrics.increment("session_revocations")
        self.publisher.publish_event(
            action="Logout All Devices",
            resource_type="Session",
            category="Security",
            user_id=user_id,
            status="success",
        )

    def get_user_active_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        sessions = self.repo.get_active_sessions_for_user(user_id)
        return [
            {
                "id": s.id,
                "uuid": str(s.uuid),
                "device_name": s.device_name,
                "device_type": s.device_type,
                "browser": s.browser,
                "os": s.os,
                "client_ip": s.client_ip,
                "risk_score": s.risk_score,
                "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
            }
            for s in sessions
        ]
