"""
Intelligence Tasks — Asynchronous Background Task Processing for Knowledge Intelligence.

Refinement #6:
Non-blocking background processing for post-ingestion intelligence:
1. Metadata Enrichment
2. Classification
3. Entity Extraction
4. Relationship Detection
5. Knowledge Health recalculation
"""

import logging
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.services.metadata_enrichment_service import MetadataEnrichmentService
from app.services.document_relationship_service import DocumentRelationshipService

logger = logging.getLogger(__name__)


def run_async_document_intelligence(document_id: int) -> None:
    """
    Background worker task to enrich document metadata, extract entities,
    classify document, detect relationships, and update Qdrant payload.
    """
    db: Session = SessionLocal()
    try:
        logger.info(f"Task: Starting async intelligence processing for Document {document_id}...")

        # 1. Metadata enrichment, classification, entity extraction, Qdrant payload sync
        enrichment_svc = MetadataEnrichmentService(db)
        meta = enrichment_svc.enrich_document(document_id)

        # 2. Document relationship detection (vector-similarity first)
        rel_svc = DocumentRelationshipService(db)
        rels = rel_svc.detect_relationships(document_id)

        logger.info(
            f"Task: Completed intelligence for Doc {document_id} "
            f"(Category: {meta.classification}, Relationships: {len(rels)})"
        )
    except Exception as e:
        logger.error(f"Task: Intelligence processing failed for Doc {document_id}: {e}")
    finally:
        db.close()
