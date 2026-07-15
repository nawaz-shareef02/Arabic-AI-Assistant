import uuid as py_uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, Response, File, UploadFile, Form, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["DOCUMENTS"])

@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    knowledge_base_uuid: py_uuid.UUID = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = DocumentService(db)
    db_doc = await service.upload_document(file, kb_uuid=knowledge_base_uuid, creator_id=current_user.id)
    background_tasks.add_task(service.process_document, db_doc.uuid, current_user.id)
    return db_doc

@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    request: DocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = DocumentService(db)
    return service.create_doc(request, creator_id=current_user.id)

@router.get("", response_model=List[DocumentResponse], status_code=status.HTTP_200_OK)
def list_documents(
    kb_uuid: Optional[py_uuid.UUID] = Query(None, description="Filter by parent Knowledge Base UUID"),
    search: Optional[str] = Query(None, description="Search term for filename"),
    sort_by: str = Query("created_at", description="Sort field (filename, file_size, created_at, updated_at)"),
    sort_order: str = Query("desc", description="Sort order (asc, desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = DocumentService(db)
    return service.list_docs(
        owner_id=current_user.id,
        kb_uuid=kb_uuid,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size
    )

@router.get("/{uuid}", response_model=DocumentResponse, status_code=status.HTTP_200_OK)
def get_document(
    uuid: py_uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = DocumentService(db)
    return service.get_doc(uuid, owner_id=current_user.id)

@router.patch("/{uuid}", response_model=DocumentResponse, status_code=status.HTTP_200_OK)
def update_document(
    uuid: py_uuid.UUID,
    request: DocumentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = DocumentService(db)
    return service.update_doc(uuid, request, owner_id=current_user.id)

@router.delete("/{uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    uuid: py_uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = DocumentService(db)
    service.delete_doc(uuid, owner_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)