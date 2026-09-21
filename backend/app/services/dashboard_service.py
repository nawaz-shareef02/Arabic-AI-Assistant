import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import func, case
from sqlalchemy.orm import Session, joinedload
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document

class DashboardService:
    def __init__(self, db: Session):
        self.db = db

    def get_summary(self, owner_id: int) -> Dict[str, Any]:
        # 1. Count active knowledge bases owned by the user
        kb_count = (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.owner_id == owner_id,
                KnowledgeBase.is_active == True,
            )
            .count()
        )

        # 2. Consolidated document aggregation query: counts by status, total, storage bytes, last upload
        stats = (
            self.db.query(
                func.count(Document.id).label("doc_count"),
                func.coalesce(func.sum(case((Document.status == "Uploaded", 1), else_=0)), 0).label("uploaded_count"),
                func.coalesce(func.sum(case((Document.status == "Parsing", 1), else_=0)), 0).label("parsing_count"),
                func.coalesce(func.sum(case((Document.status == "Parsed", 1), else_=0)), 0).label("parsed_count"),
                func.coalesce(func.sum(case((Document.status == "Failed", 1), else_=0)), 0).label("failed_count"),
                func.coalesce(func.sum(Document.file_size), 0).label("storage_bytes"),
                func.max(Document.created_at).label("last_upload"),
            )
            .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
            .filter(
                KnowledgeBase.owner_id == owner_id,
                KnowledgeBase.is_active == True,
            )
            .first()
        )

        doc_count = int(stats.doc_count) if stats and stats.doc_count else 0
        uploaded_count = int(stats.uploaded_count) if stats and stats.uploaded_count else 0
        parsing_count = int(stats.parsing_count) if stats and stats.parsing_count else 0
        parsed_count_status = int(stats.parsed_count) if stats and stats.parsed_count else 0
        failed_count = int(stats.failed_count) if stats and stats.failed_count else 0
        storage_bytes = int(stats.storage_bytes) if stats and stats.storage_bytes else 0
        storage_mb = round(storage_bytes / (1024 * 1024), 2)
        last_upload = stats.last_upload if stats else None

        # 3. Retrieve recent activity: 5 most recent documents with eager-loaded KB
        recent_docs = (
            self.db.query(Document)
            .options(joinedload(Document.knowledge_base))
            .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
            .filter(
                KnowledgeBase.owner_id == owner_id,
                KnowledgeBase.is_active == True,
            )
            .order_by(Document.created_at.desc())
            .limit(5)
            .all()
        )

        recent_activity = []
        for doc in recent_docs:
            recent_activity.append({
                "uuid": doc.uuid,
                "filename": doc.filename,
                "mime_type": doc.mime_type,
                "status": doc.status,
                "created_at": doc.created_at,
                "kb_name": doc.knowledge_base.name if doc.knowledge_base else "",
                "kb_uuid": doc.knowledge_base.uuid if doc.knowledge_base else None,
            })

        return {
            "knowledge_bases": kb_count,
            "documents": doc_count,
            "storage_used": storage_bytes,
            "storage_used_mb": storage_mb,
            "last_upload": last_upload,
            "recent_activity": recent_activity,
            "uploaded_docs": uploaded_count,
            "parsing_docs": parsing_count,
            "parsed_docs": parsed_count_status,
            "failed_docs": failed_count,
        }
