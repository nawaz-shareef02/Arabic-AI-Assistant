"""
SessionRepository — Data Access for User Sessions, Token Families & Blacklisting.
"""

import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.user_session import UserSession
from app.core.rate_limit import redis_client


class SessionRepository:
    _memory_blacklist = set()

    def __init__(self, db: Session):
        self.db = db

    def create_session(
        self,
        user_id: int,
        family_id: str,
        refresh_token_hash: str,
        expires_at: datetime.datetime,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        device_type: Optional[str] = None,
        browser: Optional[str] = None,
        os: Optional[str] = None,
        client_ip: Optional[str] = None,
        risk_score: float = 0.0,
    ) -> UserSession:
        sess = UserSession(
            user_id=user_id,
            family_id=family_id,
            refresh_token_hash=refresh_token_hash,
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            browser=browser,
            os=os,
            client_ip=client_ip,
            risk_score=risk_score,
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(sess)
        self.db.commit()
        self.db.refresh(sess)
        return sess

    def get_by_refresh_hash(self, token_hash: str) -> Optional[UserSession]:
        return (
            self.db.query(UserSession)
            .filter(UserSession.refresh_token_hash == token_hash)
            .first()
        )

    def get_active_sessions_for_user(self, user_id: int) -> List[UserSession]:
        return (
            self.db.query(UserSession)
            .filter(UserSession.user_id == user_id, UserSession.is_active == True)
            .order_by(UserSession.last_active_at.desc())
            .all()
        )

    def invalidate_token_family(self, family_id: str) -> None:
        """Refinement #9: Invalidates all sessions in a compromised token family."""
        sessions = self.db.query(UserSession).filter(UserSession.family_id == family_id).all()
        for s in sessions:
            s.is_active = False
            self.blacklist_token(s.refresh_token_hash)
        self.db.commit()

    def invalidate_all_user_sessions(self, user_id: int) -> None:
        sessions = self.db.query(UserSession).filter(UserSession.user_id == user_id).all()
        for s in sessions:
            s.is_active = False
            self.blacklist_token(s.refresh_token_hash)
        self.db.commit()

    def blacklist_token(self, token_hash: str, ttl_seconds: int = 86400 * 30) -> None:
        if redis_client:
            try:
                redis_client.setex(f"token_blacklist:{token_hash}", ttl_seconds, "revoked")
            except Exception:
                self._memory_blacklist.add(token_hash)
        else:
            self._memory_blacklist.add(token_hash)

    def is_token_blacklisted(self, token_hash: str) -> bool:
        if redis_client:
            try:
                return redis_client.exists(f"token_blacklist:{token_hash}") > 0
            except Exception:
                return token_hash in self._memory_blacklist
        return token_hash in self._memory_blacklist
