"""
OrganizationRepository — Data Access for Multi-Tenant Organizations & Workspaces.
"""

from typing import List, Optional
from sqlalchemy.orm import Session, selectinload
from app.models.organization import Organization, OrganizationMember
from app.models.workspace import Workspace


class OrganizationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, org_id: int) -> Optional[Organization]:
        return self.db.query(Organization).filter(Organization.id == org_id).first()

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        return self.db.query(Organization).filter(Organization.slug == slug).first()

    def create(
        self,
        name: str,
        slug: str,
        domain: Optional[str] = None,
        monthly_token_budget: Optional[int] = None,
        max_storage_mb: Optional[int] = None,
        max_documents: Optional[int] = None,
    ) -> Organization:
        org = Organization(
            name=name,
            slug=slug,
            domain=domain,
            is_active=True,
            monthly_token_budget=monthly_token_budget,
            max_storage_mb=max_storage_mb,
            max_documents=max_documents,
        )
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)
        return org

    def update_quotas(
        self,
        org_id: int,
        monthly_token_budget: Optional[int] = None,
        max_storage_mb: Optional[int] = None,
        max_documents: Optional[int] = None,
    ) -> Optional[Organization]:
        """
        Partial quota update — only fields explicitly passed (non-None sentinel)
        are written.  Fields left as None are NOT reset.

        AI-8 Pre-C: the previous implementation unconditionally overwrote all
        three quota fields, meaning a call that supplied only monthly_token_budget
        would silently set max_storage_mb=None and max_documents=None (removing
        those limits).  This is now fixed to preserve unmodified fields.

        To explicitly REMOVE a quota limit (set it to NULL / unlimited), the
        caller must use a dedicated sentinel or a future PATCH schema that
        distinguishes "not supplied" from "explicitly set to None".  For now
        this is an internal helper with no public route, so we use keyword
        presence as the signal.
        """
        org = self.get_by_id(org_id)
        if not org:
            return None
        if monthly_token_budget is not None:
            org.monthly_token_budget = monthly_token_budget
        if max_storage_mb is not None:
            org.max_storage_mb = max_storage_mb
        if max_documents is not None:
            org.max_documents = max_documents
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
            .options(selectinload(Organization.workspaces))
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
