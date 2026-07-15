import uuid as py_uuid
from typing import List, Optional
from sqlalchemy import or_, desc, asc
from sqlalchemy.orm import Session
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate

def create_kb(db: Session, kb_in: KnowledgeBaseCreate, owner_id: int) -> KnowledgeBase:
    db_kb = KnowledgeBase(
        name=kb_in.name,
        description=kb_in.description,
        owner_id=owner_id,
        created_by=owner_id,
        updated_by=owner_id,
        is_active=True
    )
    db.add(db_kb)
    db.commit()
    db.refresh(db_kb)
    return db_kb

def get_kb_by_uuid(db: Session, kb_uuid: py_uuid.UUID, owner_id: int) -> Optional[KnowledgeBase]:
    return db.query(KnowledgeBase).filter(
        KnowledgeBase.uuid == kb_uuid,
        KnowledgeBase.owner_id == owner_id,
        KnowledgeBase.is_active == True
    ).first()

def get_kbs(
    db: Session,
    owner_id: int,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20
) -> List[KnowledgeBase]:
    query = db.query(KnowledgeBase).filter(
        KnowledgeBase.owner_id == owner_id,
        KnowledgeBase.is_active == True
    )

    # Search filter
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                KnowledgeBase.name.ilike(search_filter),
                KnowledgeBase.description.ilike(search_filter)
            )
        )

    # Sorting
    order_column = getattr(KnowledgeBase, sort_by, KnowledgeBase.created_at)
    if sort_order == "desc":
        query = query.order_by(desc(order_column))
    else:
        query = query.order_by(asc(order_column))

    # Pagination
    skip = (page - 1) * page_size
    query = query.offset(skip).limit(page_size)

    return query.all()

def update_kb(
    db: Session,
    kb: KnowledgeBase,
    kb_in: KnowledgeBaseUpdate,
    updater_id: int
) -> KnowledgeBase:
    update_data = kb_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(kb, field, value)
    
    # Audit tracking
    kb.updated_by = updater_id
    
    db.commit()
    db.refresh(kb)
    return kb

def soft_delete_kb(db: Session, kb: KnowledgeBase, updater_id: int) -> KnowledgeBase:
    kb.is_active = False
    kb.updated_by = updater_id
    db.commit()
    db.refresh(kb)
    return kb
