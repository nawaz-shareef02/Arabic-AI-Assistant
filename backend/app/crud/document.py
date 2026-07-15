import uuid as py_uuid
from typing import List, Optional
from sqlalchemy import or_, desc, asc
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.schemas.document import DocumentCreate, DocumentUpdate

def create_doc(db: Session, doc_in: DocumentCreate, kb_id: int, creator_id: int) -> Document:
    db_doc = Document(
        knowledge_base_id=kb_id,
        filename=doc_in.filename,
        storage_path=doc_in.storage_path,
        mime_type=doc_in.mime_type,
        file_size=doc_in.file_size,
        language=doc_in.language,
        status="Queued",  # Default status
        created_by=creator_id,
        updated_by=creator_id
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)
    return db_doc

def get_doc_by_uuid(db: Session, doc_uuid: py_uuid.UUID, owner_id: int) -> Optional[Document]:
    return db.query(Document).join(KnowledgeBase).filter(
        Document.uuid == doc_uuid,
        KnowledgeBase.owner_id == owner_id,
        KnowledgeBase.is_active == True
    ).first()

def get_docs(
    db: Session,
    owner_id: int,
    kb_id: Optional[int] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20
) -> List[Document]:
    query = db.query(Document).join(KnowledgeBase).filter(
        KnowledgeBase.owner_id == owner_id,
        KnowledgeBase.is_active == True
    )

    if kb_id is not None:
        query = query.filter(Document.knowledge_base_id == kb_id)

    # Search filter (on filename)
    if search:
        query = query.filter(Document.filename.ilike(f"%{search}%"))

    # Sorting
    order_column = getattr(Document, sort_by, Document.created_at)
    if sort_order == "desc":
        query = query.order_by(desc(order_column))
    else:
        query = query.order_by(asc(order_column))

    # Pagination
    skip = (page - 1) * page_size
    query = query.offset(skip).limit(page_size)

    return query.all()

def update_doc(
    db: Session,
    doc: Document,
    doc_in: DocumentUpdate,
    updater_id: int,
    new_kb_id: Optional[int] = None
) -> Document:
    update_data = doc_in.model_dump(exclude_unset=True)
    
    # Exclude knowledge_base_uuid since it maps to the integer relationship ID
    update_data.pop("knowledge_base_uuid", None)
    
    for field, value in update_data.items():
        setattr(doc, field, value)
    
    if new_kb_id is not None:
        doc.knowledge_base_id = new_kb_id

    doc.updated_by = updater_id
    
    db.commit()
    db.refresh(doc)
    return doc

def delete_doc(db: Session, doc: Document) -> None:
    db.delete(doc)
    db.commit()
