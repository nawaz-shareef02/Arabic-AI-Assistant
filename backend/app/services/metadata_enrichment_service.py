"""
MetadataEnrichmentService — Document Enrichment & PostgreSQL / Qdrant Synchronization.

Orchestrates post-parsing enrichment:
1. Title, Author, Summary, Keywords, Topics extraction
2. ClassificationService classification
3. EntityExtractionService entity extraction
4. Saves records in `document_metadata` and `document_entities`
5. Updates `documents.classification`
6. Synchronizes enriched metadata into Qdrant point payloads
"""

import logging
import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.models.document_metadata import DocumentMetadata
from app.models.document_entity import DocumentEntity
from app.services.classification_service import ClassificationService
from app.services.entity_extraction_service import EntityExtractionService
from app.services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)


class MetadataEnrichmentService:
    def __init__(self, db: Session):
        self.db = db
        self.classifier = ClassificationService()
        self.entity_extractor = EntityExtractionService()
        self.qdrant_service = QdrantService()

    def enrich_document(self, document_id: int) -> DocumentMetadata:
        doc = self.db.query(Document).filter(Document.id == document_id).first()
        if not doc or not doc.parsed_document:
            raise ValueError(f"Document {document_id} or parsed text not found.")

        parsed_text = doc.parsed_document.parsed_text
        filename = doc.filename

        # 1. Title heuristic
        lines = [l.strip() for l in parsed_text.splitlines() if l.strip()]
        title = lines[0][:200] if lines else filename

        # 2. Summary heuristic (first 2 paragraphs / 500 chars)
        summary = " ".join(lines[:4])[:500] if lines else ""

        # 3. Classify document
        classification = self.classifier.classify_document(parsed_text, filename)
        doc.classification = classification

        # 4. Extract topics & keywords
        words = [w.strip(".,!?:;\"'").lower() for w in parsed_text.split() if len(w) > 4]
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)
        keywords = sorted_words[:10]
        topics = [classification] + sorted_words[:3]

        # 5. Save or update DocumentMetadata
        metadata = self.db.query(DocumentMetadata).filter(
            DocumentMetadata.document_id == doc.id
        ).first()

        if not metadata:
            metadata = DocumentMetadata(
                document_id=doc.id,
                title=title,
                author="Internal Corporate User",
                creation_date=doc.created_at,
                classification=classification,
                summary=summary,
                keywords=keywords,
                topics=topics,
            )
            self.db.add(metadata)
        else:
            metadata.title = title
            metadata.classification = classification
            metadata.summary = summary
            metadata.keywords = keywords
            metadata.topics = topics

        # 6. Extract and save entities
        extracted_entities = self.entity_extractor.extract_entities(parsed_text)
        # Clear existing entities if re-running
        self.db.query(DocumentEntity).filter(DocumentEntity.document_id == doc.id).delete()

        entity_models = []
        for ent in extracted_entities:
            entity_models.append(
                DocumentEntity(
                    document_id=doc.id,
                    entity_text=ent["text"],
                    entity_type=ent["type"],
                    language=ent["language"],
                    confidence=ent["confidence"],
                )
            )
        self.db.add_all(entity_models)
        self.db.commit()
        self.db.refresh(metadata)

        # 7. Synchronize payload into Qdrant vector database
        self._sync_qdrant_payload(doc, metadata, extracted_entities)

        logger.info(f"MetadataEnrichmentService: Enriched doc {doc.id} ({doc.filename}) → Category: {classification}")
        return metadata

    def _sync_qdrant_payload(
        self,
        doc: Document,
        metadata: DocumentMetadata,
        entities: List[Dict[str, Any]],
    ) -> None:
        """Update Qdrant points payload with enriched metadata."""
        try:
            entity_texts = [e["text"] for e in entities[:15]]
            payload_update = {
                "classification": metadata.classification,
                "author": metadata.author or "Internal Corporate User",
                "topics": metadata.topics or [],
                "entities": entity_texts,
                "document_type": doc.mime_type,
                "language": doc.language or "EN",
            }

            # Filter Qdrant points by parsed_document_id and set payload
            if doc.parsed_document:
                self.qdrant_service.client.set_payload(
                    collection_name=self.qdrant_service.collection_name,
                    payload=payload_update,
                    points=self.qdrant_service.client.scroll(
                        collection_name=self.qdrant_service.collection_name,
                        scroll_filter={
                            "must": [
                                {
                                    "key": "parsed_document_id",
                                    "match": {"value": doc.parsed_document.id},
                                }
                            ]
                        },
                        limit=500,
                    )[0],
                )
                logger.debug(f"Qdrant payload synchronized for Document {doc.id}")
        except Exception as e:
            logger.warning(f"Failed to sync Qdrant payload for Doc {doc.id}: {e}")
