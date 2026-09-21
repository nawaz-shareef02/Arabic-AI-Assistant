"""
InvitationRepository — Data Access for Organization Invitations & SHA-256 Token Lookup.
"""

from typing import List, Optional
import datetime
import uuid as py_uuid
from sqlalchemy.orm import Session, joinedload
from app.models.organization_invitation import OrganizationInvitation


class InvitationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_token_hash(
        self, token_hash: str, for_update: bool = False
    ) -> Optional[OrganizationInvitation]:
        query = self.db.query(OrganizationInvitation).filter(
            OrganizationInvitation.token_hash == token_hash
        )
        if for_update:
            query = query.with_for_update()
        return query.first()

    def get_by_uuid(
        self, inv_uuid: str, org_id: Optional[int] = None
    ) -> Optional[OrganizationInvitation]:
        try:
            parsed_uuid = py_uuid.UUID(inv_uuid)
        except (ValueError, TypeError):
            return None

        query = self.db.query(OrganizationInvitation).filter(
            OrganizationInvitation.uuid == parsed_uuid
        )
        if org_id is not None:
            query = query.filter(OrganizationInvitation.organization_id == org_id)
        return query.first()

    def get_pending_by_org(self, org_id: int) -> List[OrganizationInvitation]:
        return (
            self.db.query(OrganizationInvitation)
            .options(joinedload(OrganizationInvitation.role))
            .filter(
                OrganizationInvitation.organization_id == org_id,
                OrganizationInvitation.status == "pending",
            )
            .order_by(OrganizationInvitation.created_at.desc())
            .all()
        )

    def get_all_by_org(
        self, org_id: int, status: Optional[str] = None
    ) -> List[OrganizationInvitation]:
        query = (
            self.db.query(OrganizationInvitation)
            .options(joinedload(OrganizationInvitation.role))
            .filter(
                OrganizationInvitation.organization_id == org_id
            )
        )
        if status:
            query = query.filter(OrganizationInvitation.status == status)
        return query.order_by(OrganizationInvitation.created_at.desc()).all()

    def get_active_by_org_and_email(
        self, org_id: int, email: str
    ) -> Optional[OrganizationInvitation]:
        return (
            self.db.query(OrganizationInvitation)
            .filter(
                OrganizationInvitation.organization_id == org_id,
                OrganizationInvitation.email == email.lower().strip(),
                OrganizationInvitation.status == "pending",
            )
            .first()
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
            email=email.lower().strip(),
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

    def update_status(
        self,
        inv_id: int,
        new_status: str,
        accepted_at: Optional[datetime.datetime] = None,
        revoked_at: Optional[datetime.datetime] = None,
    ) -> Optional[OrganizationInvitation]:
        inv = (
            self.db.query(OrganizationInvitation)
            .filter(OrganizationInvitation.id == inv_id)
            .first()
        )
        if inv:
            inv.status = new_status
            if accepted_at is not None:
                inv.accepted_at = accepted_at
            if revoked_at is not None:
                inv.revoked_at = revoked_at
            self.db.commit()
            self.db.refresh(inv)
        return inv
