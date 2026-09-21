import uuid as py_uuid
import time
import logging
import hashlib
from typing import List, Optional
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentStatus
from app.crud import document as crud_doc
from app.services.storage_service import StorageService
from app.services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)

class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.storage_service = StorageService()
        self.qdrant_service = QdrantService()

    def _get_kb_or_raise(self, kb_uuid: py_uuid.UUID, owner_id: int) -> KnowledgeBase:
        kb = self.db.query(KnowledgeBase).filter(
            KnowledgeBase.uuid == kb_uuid,
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.is_active == True
        ).first()
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge Base not found"
            )
        return kb

    async def upload_document(
        self,
        file: UploadFile,
        kb_uuid: py_uuid.UUID,
        creator_id: int
    ) -> Document:
        start_time = time.time()
        
        # 1. Assert target knowledge base exists and is owned by user
        kb = self._get_kb_or_raise(kb_uuid, creator_id)
        
        # 2. Generate a new document UUID
        doc_uuid = py_uuid.uuid4()
        
        # 3. Validate and store file
        storage_service = StorageService()
        file_size = await storage_service.validate_file(file)
        stored_path = await storage_service.store_file(file, kb_uuid, doc_uuid)
        
        # 4. Calculate SHA-256 checksum
        sha256 = hashlib.sha256()
        with open(stored_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        sha256_hash = sha256.hexdigest()
        
        # Check for duplicates in the same KB based on SHA256
        import os
        duplicate = self.db.query(Document).filter(
            Document.knowledge_base_id == kb.id,
            Document.sha256_hash == sha256_hash
        ).first()
        if duplicate:
            if os.path.exists(stored_path):
                os.remove(stored_path)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A document with the same content already exists in this knowledge base."
            )
        
        # 5. Insert Document metadata record
        db_doc = Document(
            uuid=doc_uuid,
            knowledge_base_id=kb.id,
            filename=file.filename or "file",
            storage_path=stored_path,
            mime_type=file.content_type or "application/octet-stream",
            language=None,  # Null on upload
            status=DocumentStatus.QUEUED,  # Waiting for Celery worker (P0-2)
            file_size=file_size,
            sha256_hash=sha256_hash,
            created_by=creator_id,
            updated_by=creator_id
        )
        self.db.add(db_doc)
        self.db.commit()
        self.db.refresh(db_doc)
        
        logger = logging.getLogger("app.services.document_service")
        logger.info(f"AUDIT | Action: doc_upload | Doc: {doc_uuid} | KB: {kb_uuid} | User: {creator_id} | Status: success")
        
        # 6. Structured Logging
        duration = time.time() - start_time
        logger = logging.getLogger("app.services.document_service")
        logger.info(
            f"User uploaded document | "
            f"KB UUID: {kb_uuid} | "
            f"Document UUID: {doc_uuid} | "
            f"File Size: {file_size} bytes | "
            f"Duration: {duration:.4f}s"
        )
        
        return db_doc

    # -------------------------------------------------------------------------
    # NOTE (P0-2): process_document() has been moved to the Celery task
    # app.tasks.indexing_tasks.process_document_async.  The FastAPI router
    # dispatches that task via .delay() immediately after upload_document()
    # returns.  No document processing occurs in this service or in the
    # FastAPI web process.
    # -------------------------------------------------------------------------


    def create_doc(self, doc_in: DocumentCreate, creator_id: int) -> Document:
        # Assert parent knowledge base exists and is owned by creator
        kb = self._get_kb_or_raise(doc_in.knowledge_base_uuid, creator_id)
        return crud_doc.create_doc(self.db, doc_in, kb.id, creator_id)

    def get_doc(self, doc_uuid: py_uuid.UUID, owner_id: int) -> Document:
        doc = crud_doc.get_doc_by_uuid(self.db, doc_uuid, owner_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        return doc

    def list_docs(
        self,
        owner_id: int,
        kb_uuid: Optional[py_uuid.UUID] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20
    ) -> List[Document]:
        # Validate sort fields
        allowed_sort_fields = {"filename", "file_size", "created_at", "updated_at"}
        if sort_by not in allowed_sort_fields:
            sort_by = "created_at"
        if sort_order not in {"asc", "desc"}:
            sort_order = "desc"

        kb_id = None
        if kb_uuid is not None:
            kb = self._get_kb_or_raise(kb_uuid, owner_id)
            kb_id = kb.id

        return crud_doc.get_docs(
            self.db,
            owner_id=owner_id,
            kb_id=kb_id,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size
        )

    def update_doc(
        self,
        doc_uuid: py_uuid.UUID,
        doc_in: DocumentUpdate,
        owner_id: int
    ) -> Document:
        doc = self.get_doc(doc_uuid, owner_id)
        
        new_kb_id = None
        if doc_in.knowledge_base_uuid is not None:
            # Validate destination knowledge base is active and owned by user
            kb = self._get_kb_or_raise(doc_in.knowledge_base_uuid, owner_id)
            new_kb_id = kb.id
            
        return crud_doc.update_doc(self.db, doc, doc_in, owner_id, new_kb_id)

    def delete_doc(self, doc_uuid: py_uuid.UUID, owner_id: int) -> None:
        """
        Idempotent and failure-safe document deletion (SEC-REQ-04).

        Consistency Ordering & Failure Mode Semantics:
        1. Extract metadata (storage_path, parsed_document_id, kb_id, org_id) before
           PostgreSQL cascades execute.
        2. Delete and commit the PostgreSQL document record first.
           - Ensures DB connection/locks are NOT held during external disk/network I/O.
           - Guarantees that if a PostgreSQL error/rollback occurs, the system does NOT
             permanently lose physical files or Qdrant vectors.
        3. Delete Qdrant vector points idempotently.
           - Safely catches and logs errors; missing points/collection do not crash.
        4. Delete physical file from storage idempotently.
           - Safely catches and logs errors; missing files do not crash.
        Residual Failure Mode:
        - If Qdrant or filesystem cleanup encounters transient downtime after PostgreSQL
          deletion has committed, the document is already non-existent in PostgreSQL (preventing
          API retrieval or FTS matches), and residual vectors/files can be pruned without
          inconsistent database references.
        """
        doc = self.get_doc(doc_uuid, owner_id)

        # 1. Pre-fetch cascading attributes before database deletion
        storage_path = doc.storage_path
        parsed_doc_id = doc.parsed_document.id if doc.parsed_document else None
        kb_id = doc.knowledge_base_id
        org_id = doc.knowledge_base.organization_id if doc.knowledge_base else None

        # 2. Delete and commit PostgreSQL record first (releases DB transaction)
        crud_doc.delete_doc(self.db, doc)

        # 3. Clean up Qdrant vector points associated with this document (idempotent & safe)
        if parsed_doc_id is not None:
            try:
                self.qdrant_service.delete_document_vectors(
                    parsed_document_id=parsed_doc_id,
                    organization_id=org_id,
                    knowledge_base_id=kb_id,
                )
            except Exception as exc:
                logger.warning(
                    f"Safe cleanup: failed to delete Qdrant vectors for parsed_doc {parsed_doc_id} (doc_uuid: {doc_uuid}): {exc}"
                )

        # 4. Clean up physical stored file on disk (idempotent & safe)
        if storage_path:
            try:
                self.storage_service.delete_file(storage_path)
            except Exception as exc:
                logger.warning(
                    f"Safe cleanup: failed to delete physical file {storage_path} (doc_uuid: {doc_uuid}): {exc}"
                )
