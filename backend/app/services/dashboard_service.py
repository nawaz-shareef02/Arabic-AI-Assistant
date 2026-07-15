import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document

class DashboardService:
    def __init__(self, db: Session):
        self.db = db

    def get_summary(self, owner_id: int) -> Dict[str, Any]:
        # Count active knowledge bases owned by the user
        kb_count = self.db.query(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True
        ).count()

        # Count documents inside active knowledge bases owned by the user
        doc_count = self.db.query(Document).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True
        ).count()

        # Count documents by status inside active knowledge bases owned by the user
        uploaded_count = self.db.query(Document).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True,
            Document.status == "Uploaded"
        ).count()

        parsing_count = self.db.query(Document).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True,
            Document.status == "Parsing"
        ).count()

        parsed_count_status = self.db.query(Document).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True,
            Document.status == "Parsed"
        ).count()

        failed_count = self.db.query(Document).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True,
            Document.status == "Failed"
        ).count()

        # Calculate sum of document sizes in bytes
        storage_bytes = self.db.query(func.sum(Document.file_size)).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True
        ).scalar() or 0

        # Convert to MB (rounded to 2 decimal places)
        storage_mb = round(storage_bytes / (1024 * 1024), 2)

        # Retrieve last upload timestamp
        last_upload = self.db.query(func.max(Document.created_at)).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True
        ).scalar()

        # Retrieve recent activity: 5 most recent documents
        recent_docs = self.db.query(Document).join(KnowledgeBase).filter(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True
        ).order_by(Document.created_at.desc()).limit(5).all()

        recent_activity = []
        for doc in recent_docs:
            recent_activity.append({
                "uuid": doc.uuid,
                "filename": doc.filename,
                "mime_type": doc.mime_type,
                "status": doc.status,
                "created_at": doc.created_at,
                "kb_name": doc.knowledge_base.name,
                "kb_uuid": doc.knowledge_base.uuid
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
            "failed_docs": failed_count
        }
