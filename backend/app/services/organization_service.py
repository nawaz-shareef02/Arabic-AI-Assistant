"""
OrganizationService — Full Enterprise Organization Lifecycle & Activity Timeline Feed.

Refinement #7: Soft Delete Strategy (is_deleted, deleted_at, deleted_by_id).
Refinement #10: Organization Activity Timeline Feed.
"""

import datetime
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.audit_repository import AuditRepository
from app.services.audit_event_publisher import AuditEventPublisher

logger = logging.getLogger("app.services.organization_service")


class OrganizationService:
    def __init__(self, db: Session):
        self.db = db
        self.org_repo = OrganizationRepository(db)
        self.role_repo = RoleRepository(db)
        self.audit_repo = AuditRepository(db)
        self.publisher = AuditEventPublisher(db)

    def create_organization(self, name: str, slug: str, creator_user: User) -> Organization:
        existing = self.org_repo.get_by_slug(slug)
        if existing:
            raise HTTPException(status_code=400, detail="Organization slug already exists.")

        org = self.org_repo.create(name=name, slug=slug)
        self.org_repo.add_member(org.id, creator_user.id)

        org_admin_role = self.role_repo.get_by_name("Organization Admin")
        if org_admin_role:
            self.role_repo.assign_role_to_user(creator_user.id, org_admin_role.id, org.id)

        self.publisher.publish_event(
            action="Organization Created",
            resource_type="Organization",
            category="Organization",
            user_id=creator_user.id,
            organization_id=org.id,
            resource_id=str(org.uuid),
            metadata_json={"name": name, "slug": slug},
        )
        return org

    def soft_delete_organization(self, org_id: int, user: User) -> None:
        """Refinement #7: Soft deletion pattern."""
        org = self.org_repo.get_by_id(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        org.is_deleted = True
        org.is_active = False
        org.deleted_at = datetime.datetime.now(datetime.timezone.utc)
        org.deleted_by_id = user.id
        self.db.commit()

        self.publisher.publish_event(
            action="Organization Deleted",
            resource_type="Organization",
            category="Organization",
            user_id=user.id,
            organization_id=org_id,
            resource_id=str(org.uuid),
        )

    def get_organization_members(self, org_id: int) -> List[Dict[str, Any]]:
        members = (
            self.db.query(OrganizationMember)
            .filter(OrganizationMember.organization_id == org_id)
            .all()
        )
        result = []
        for m in members:
            u = m.user
            user_roles = self.role_repo.get_user_roles(u.id)
            role_names = [r.name for r in user_roles if r.organization_id == org_id or r.is_system_role]
            result.append({
                "id": m.id,
                "user_id": u.id,
                "user_uuid": str(u.uuid),
                "full_name": u.full_name,
                "email": u.email,
                "roles": role_names,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            })
        return result

    def get_activity_feed(self, org_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Refinement #10: Organization Activity Timeline Feed (Recent 50 Events)."""
        logs, _ = self.audit_repo.query_logs(org_id=org_id, page=1, page_size=limit)
        return [
            {
                "id": log.id,
                "uuid": str(log.uuid),
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "user_id": log.user_id,
                "user_email": log.user.email if log.user else "System",
                "category": log.category,
                "action": log.action,
                "resource_type": log.resource_type,
                "status": log.status,
            }
            for log in logs
        ]
