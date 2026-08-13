"""
OrganizationRepository — Data Access for Multi-Tenant Organizations & Workspaces.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.organization import Organization, OrganizationMember
from app.models.workspace import Workspace


class OrganizationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, org_id: int) -> Optional[Organization]:
        return self.db.query(Organization).filter(Organization.id == org_id).first()

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        return self.db.query(Organization).filter(Organization.slug == slug).first()

    def create(self, name: str, slug: str, domain: Optional[str] = None) -> Organization:
        org = Organization(name=name, slug=slug, domain=domain, is_active=True)
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)
        return org

    def add_member(self, org_id: int, user_id: int) -> OrganizationMember:
        existing = (
            self.db.query(OrganizationMember)
            .filter(OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user_id)
            .first()
        )
        if existing:
            return existing

        member = OrganizationMember(organization_id=org_id, user_id=user_id)
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def get_user_organizations(self, user_id: int) -> List[Organization]:
        return (
            self.db.query(Organization)
            .join(OrganizationMember, Organization.id == OrganizationMember.organization_id)
            .filter(OrganizationMember.user_id == user_id)
            .all()
        )

    def create_workspace(self, org_id: int, name: str, description: str = "") -> Workspace:
        ws = Workspace(organization_id=org_id, name=name, description=description, is_active=True)
        self.db.add(ws)
        self.db.commit()
        self.db.refresh(ws)
        return ws
