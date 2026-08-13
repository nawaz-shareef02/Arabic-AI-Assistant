"""
InvitationRepository — Data Access for Organization Invitations & SHA-256 Token Lookup.
"""

from typing import List, Optional
import datetime
from sqlalchemy.orm import Session
from app.models.organization_invitation import OrganizationInvitation


class InvitationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_token_hash(self, token_hash: str) -> Optional[OrganizationInvitation]:
        return (
            self.db.query(OrganizationInvitation)
            .filter(OrganizationInvitation.token_hash == token_hash)
            .first()
        )

    def get_pending_by_org(self, org_id: int) -> List[OrganizationInvitation]:
        return (
            self.db.query(OrganizationInvitation)
            .filter(
                OrganizationInvitation.organization_id == org_id,
                OrganizationInvitation.status == "pending",
            )
            .order_by(OrganizationInvitation.created_at.desc())
            .all()
        )

    def create(
        self,
        org_id: int,
        email: str,
        role_id: int,
        token_hash: str,
        invited_by_id: int,
        expires_at: datetime.datetime,
    ) -> OrganizationInvitation:
        inv = OrganizationInvitation(
            organization_id=org_id,
            email=email,
            role_id=role_id,
            token_hash=token_hash,
            invited_by_id=invited_by_id,
            expires_at=expires_at,
            status="pending",
        )
        self.db.add(inv)
        self.db.commit()
        self.db.refresh(inv)
        return inv

    def update_status(self, inv_id: int, new_status: str) -> Optional[OrganizationInvitation]:
        inv = self.db.query(OrganizationInvitation).filter(OrganizationInvitation.id == inv_id).first()
        if inv:
            inv.status = new_status
            self.db.commit()
            self.db.refresh(inv)
        return inv
