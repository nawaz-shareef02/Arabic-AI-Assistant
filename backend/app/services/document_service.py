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

class DocumentService:
    def __init__(self, db: Session):
        self.db = db

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
            status=DocumentStatus.UPLOADED,  # "Uploaded" status for virus scan workflow
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

    def process_document(self, doc_uuid: py_uuid.UUID, owner_id: int) -> None:
        from app.database.session import SessionLocal
        from app.models.parsed_document import ParsedDocument
        from app.services.parser_service import ParserService, normalize_text, detect_language_and_confidence
        from app.services.parsers.base import DocumentParsingError
        from app.services.chunk_service import ChunkService
        from app.utils.security_scanner import SecurityScanner
        
        db = SessionLocal()
        start_time = time.time()
        logger = logging.getLogger("app.services.document_service")
        parser_name = "Unknown"
        page_count = None
        char_count = 0
        success = False
        error_msg = None
        kb_uuid = None
        doc = None
        
        try:
            # 1. Fetch document
            doc = db.query(Document).filter(Document.uuid == doc_uuid).first()
            if not doc:
                logger = logging.getLogger("app.services.document_service")
                logger.error(f"Document processing failed: Document {doc_uuid} not found")
                return
                
            # Verify ownership
            if doc.created_by != owner_id:
                logger = logging.getLogger("app.services.document_service")
                logger.error(f"AUDIT | Action: unauthorized_access | User: {owner_id} | Resource: Document {doc_uuid} | Reason: Ownership check failed")
                return

            # Verify file with security scanner
            scanner = SecurityScanner()
            if not scanner.scan_file(doc.storage_path):
                doc.status = DocumentStatus.FAILED
                db.commit()
                logger = logging.getLogger("app.services.document_service")
                logger.error(f"AUDIT | Action: doc_processing_failed | Doc: {doc_uuid} | Reason: Security threat detected")
                return
                
            kb_uuid = doc.knowledge_base.uuid
            
            # 2. Update status to PARSING
            doc.status = DocumentStatus.PARSING
            db.commit()
            db.refresh(doc)
            
            # 3. Parse content
            parser_service = ParserService()
            result = parser_service.parse_document(doc.storage_path)
            
            # Extract parser class name
            from app.services.parsers.factory import ParserFactory
            parser_obj = ParserFactory.get_parser(doc.storage_path)
            parser_name = parser_obj.__class__.__name__
            page_count = result.page_count
            
            # 4. Normalize clean text
            clean_text = normalize_text(result.text)
            char_count = len(clean_text)
            
            # 5. Detect language and confidence
            lang, confidence = detect_language_and_confidence(clean_text)
            
            # 6. Save ParsedDocument
            parsed_doc = ParsedDocument(
                document_id=doc.id,
                parsed_text=clean_text,
                parser_version=parser_name,
                language_confidence=confidence,
                char_count=char_count,
                page_count=page_count,
                processing_duration=time.time() - start_time
            )
            db.add(parsed_doc)
            db.commit()
            db.refresh(parsed_doc)
            logger.info(f"AUDIT | Action: doc_parsing | Doc: {doc_uuid} | Status: success")
            
            # 7. Generate Document Chunks
            chunk_service = ChunkService(db)
            chunk_count = chunk_service.create_chunks(parsed_doc)
            logger.info(f"AUDIT | Action: chunk_generation | Doc: {doc_uuid} | Chunks: {chunk_count} | Status: success")
            
            # Vector Indexing
            from app.services.indexing_service import IndexingService
            indexing_service = IndexingService(db)
            indexed_chunks = indexing_service.index_document(parsed_doc)
            logger.info(
                f"AUDIT | Action: vector_indexing | "
                f"Doc: {doc_uuid} | "
                f"Vectors: {indexed_chunks} | "
                f"Status: success"
            )
            
            # 8. Update Document Metadata
            doc.chunk_count = chunk_count
            doc.language = lang
            doc.status = DocumentStatus.PARSED
            doc.error_message = None  # Clear any previous error message on retry
            
            db.commit()
            db.refresh(doc)
            success = True
            
        except DocumentParsingError as e:
            error_msg = str(e)
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_msg
                db.commit()
            logger.error(f"AUDIT | Action: doc_processing_failed | Doc: {doc_uuid} | Reason: {error_msg}")
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_msg
                db.commit()
            logger.error(f"AUDIT | Action: doc_processing_failed | Doc: {doc_uuid} | Reason: {error_msg}")
        finally:
            duration = time.time() - start_time
            proc_logger = logging.getLogger("app.services.document_processing")
            status_str = "SUCCESS" if success else f"FAILED ({error_msg})"
            proc_logger.info(
                f"Document processing completed | "
                f"Document UUID: {doc_uuid} | "
                f"KB UUID: {kb_uuid} | "
                f"Duration: {duration:.4f}s | "
                f"Parser: {parser_name} | "
                f"Pages: {page_count} | "
                f"Characters: {char_count} | "
                f"Status: {status_str}"
            )
            db.close()

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
        doc = self.get_doc(doc_uuid, owner_id)
        crud_doc.delete_doc(self.db, doc)
