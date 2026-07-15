import uuid as py_uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["KNOWLEDGE_BASE"])

@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    request: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = KnowledgeBaseService(db)
    return service.create_kb(request, owner_id=current_user.id)

@router.get("", response_model=List[KnowledgeBaseResponse], status_code=status.HTTP_200_OK)
def list_knowledge_bases(
    search: Optional[str] = Query(None, description="Search term for name or description"),
    sort_by: str = Query("created_at", description="Sort field (name, created_at, updated_at)"),
    sort_order: str = Query("desc", description="Sort order (asc, desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = KnowledgeBaseService(db)
    return service.list_kbs(
        owner_id=current_user.id,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size
    )

@router.get("/{uuid}", response_model=KnowledgeBaseResponse, status_code=status.HTTP_200_OK)
def get_knowledge_base(
    uuid: py_uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = KnowledgeBaseService(db)
    return service.get_kb(uuid, owner_id=current_user.id)

@router.patch("/{uuid}", response_model=KnowledgeBaseResponse, status_code=status.HTTP_200_OK)
def update_knowledge_base(
    uuid: py_uuid.UUID,
    request: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = KnowledgeBaseService(db)
    return service.update_kb(uuid, request, owner_id=current_user.id)

@router.delete("/{uuid}", response_model=KnowledgeBaseResponse, status_code=status.HTTP_200_OK)
def delete_knowledge_base(
    uuid: py_uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = KnowledgeBaseService(db)
    return service.delete_kb(uuid, owner_id=current_user.id)