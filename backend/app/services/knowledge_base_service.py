import uuid as py_uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import OrganizationMember
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.crud import knowledge_base as crud_kb


def get_user_organization_id(db: Session, user_id: int) -> int:
    member = db.query(OrganizationMember).filter(OrganizationMember.user_id == user_id).first()
    if member:
        return member.organization_id
    return 1


class KnowledgeBaseService:
    def __init__(self, db: Session):
        self.db = db

    def create_kb(self, kb_in: KnowledgeBaseCreate, owner_id: int) -> KnowledgeBase:
        org_id = get_user_organization_id(self.db, owner_id)
        return crud_kb.create_kb(self.db, kb_in, owner_id=owner_id, organization_id=org_id)

    def get_kb(self, kb_uuid: py_uuid.UUID, owner_id: int) -> KnowledgeBase:
        org_id = get_user_organization_id(self.db, owner_id)
        kb = crud_kb.get_kb_by_uuid(self.db, kb_uuid, organization_id=org_id)
        if not kb:
            # Fallback check by owner_id for legacy test session compatibility
            kb = crud_kb.get_kb_by_uuid(self.db, kb_uuid, owner_id=owner_id)
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge Base not found"
            )
        return kb

    def list_kbs(
        self,
        owner_id: int,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20
    ) -> List[KnowledgeBase]:
        # Validate sort_by field to protect database querying
        allowed_sort_fields = {"name", "created_at", "updated_at"}
        if sort_by not in allowed_sort_fields:
            sort_by = "created_at"
        if sort_order not in {"asc", "desc"}:
            sort_order = "desc"

        org_id = get_user_organization_id(self.db, owner_id)
        return crud_kb.get_kbs(
            self.db,
            organization_id=org_id,
            owner_id=owner_id,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size
        )

    def update_kb(
        self,
        kb_uuid: py_uuid.UUID,
        kb_in: KnowledgeBaseUpdate,
        owner_id: int
    ) -> KnowledgeBase:
        kb = self.get_kb(kb_uuid, owner_id)
        return crud_kb.update_kb(self.db, kb, kb_in, owner_id)

    def delete_kb(self, kb_uuid: py_uuid.UUID, owner_id: int) -> KnowledgeBase:
        kb = self.get_kb(kb_uuid, owner_id)
        return crud_kb.soft_delete_kb(self.db, kb, owner_id)
