"""
WorkspaceService — Multi-Tenant Workspace Lifecycle Service.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.workspace import Workspace
from app.repositories.organization_repository import OrganizationRepository
from app.services.audit_event_publisher import AuditEventPublisher


class WorkspaceService:
    def __init__(self, db: Session):
        self.db = db
        self.org_repo = OrganizationRepository(db)
        self.publisher = AuditEventPublisher(db)

    def create_workspace(self, org_id: int, name: str, description: str = "", user_id: Optional[int] = None) -> Workspace:
        org = self.org_repo.get_by_id(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        ws = self.org_repo.create_workspace(org_id=org_id, name=name, description=description)
        self.publisher.publish_event(
            action="Workspace Created",
            resource_type="Workspace",
            category="Workspace",
            user_id=user_id,
            organization_id=org_id,
            workspace_id=ws.id,
            resource_id=str(ws.uuid),
            metadata_json={"name": name},
        )
        return ws

    def list_workspaces(self, org_id: int) -> List[Workspace]:
        return (
            self.db.query(Workspace)
            .filter(Workspace.organization_id == org_id, Workspace.is_active == True)
            .order_by(Workspace.created_at.desc())
            .all()
        )
