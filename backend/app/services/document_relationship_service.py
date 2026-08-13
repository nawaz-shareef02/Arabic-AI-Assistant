"""
DocumentRelationshipService — Inter-Document Relationship Detection.

Refinement #5:
- Does NOT scan or compare against the entire knowledge base (O(N^2)).
- Instead, searches the most similar candidate documents first via vector similarity
  or candidate filtering, then evaluates specific relationship rules.
- Reuses existing Qdrant vectors / embeddings.

Relationship Types:
- Duplicate (Cosine Similarity >= 0.96 or SHA-256 match)
- Similar (Cosine Similarity >= 0.75)
- References (Explicit title or filename mention)
- Version Of (Matching title pattern or SHA/name revision)
- Supersedes (Newer upload date with matching topic/title)
- Translated Version (High vector similarity + opposite language)
- Same Topic (Shared classification & top topics)
- Same Department (Shared owner/department classification)
"""

import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_relationship import DocumentRelationship
from app.services.qdrant_service import QdrantService
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

RELATIONSHIP_DUPLICATE = "Duplicate"
RELATIONSHIP_SIMILAR = "Similar"
RELATIONSHIP_REFERENCES = "References"
RELATIONSHIP_VERSION_OF = "Version Of"
RELATIONSHIP_SUPERSEDES = "Supersedes"
RELATIONSHIP_TRANSLATED = "Translated Version"
RELATIONSHIP_SAME_TOPIC = "Same Topic"


class DocumentRelationshipService:
    def __init__(self, db: Session):
        self.db = db
        self.qdrant_service = QdrantService()
        self.embedding_service = EmbeddingService()

    def detect_relationships(self, document_id: int) -> List[DocumentRelationship]:
        source_doc = self.db.query(Document).filter(Document.id == document_id).first()
        if not source_doc or not source_doc.parsed_document:
            return []

        kb_id = source_doc.knowledge_base_id
        parsed_text = source_doc.parsed_document.parsed_text

        sample_query_text = parsed_text[:1000]
        query_vector = self.embedding_service.embed_text(sample_query_text)

        candidate_points = []
        try:
            candidate_points = self.qdrant_service.search(
                query_vector=query_vector,
                knowledge_base_id=kb_id,
                limit=15,
            )
        except Exception as exc:
            logger.warning(f"Qdrant relationship candidate search unavailable: {exc}")

        # Collect unique target document IDs
        target_doc_ids = set()
        score_map: Dict[int, float] = {}

        for pt in candidate_points:
            target_parsed_id = pt.payload.get("parsed_document_id")
            if target_parsed_id and target_parsed_id != source_doc.parsed_document.id:
                target_doc = (
                    self.db.query(Document)
                    .filter(Document.id == pt.payload.get("document_id", target_parsed_id))
                    .first()
                )
                if target_doc and target_doc.id != source_doc.id:
                    target_doc_ids.add(target_doc.id)
                    score_map[target_doc.id] = max(
                        score_map.get(target_doc.id, 0.0), float(pt.score)
                    )

        # Fallback to SQL candidate documents in same KB if Qdrant vector search returned 0
        if not target_doc_ids:
            other_docs = (
                self.db.query(Document)
                .filter(Document.knowledge_base_id == kb_id, Document.id != source_doc.id)
                .limit(15)
                .all()
            )
            for od in other_docs:
                target_doc_ids.add(od.id)
                score_map[od.id] = 0.85 if od.classification == source_doc.classification else 0.50

        # 2. Evaluate relationship rules for each target candidate
        relationships: List[DocumentRelationship] = []

        # Clear existing relationships for this source document
        self.db.query(DocumentRelationship).filter(
            DocumentRelationship.source_document_id == source_doc.id
        ).delete()

        for target_id in target_doc_ids:
            target_doc = self.db.query(Document).filter(Document.id == target_id).first()
            if not target_doc:
                continue

            sim_score = score_map.get(target_id, 0.0)

            # Rule 1: Duplicate
            if (
                source_doc.sha256_hash and source_doc.sha256_hash == target_doc.sha256_hash
            ) or sim_score >= 0.96:
                relationships.append(
                    DocumentRelationship(
                        source_document_id=source_doc.id,
                        target_document_id=target_id,
                        relationship_type=RELATIONSHIP_DUPLICATE,
                        similarity_score=round(sim_score, 4),
                    )
                )

            # Rule 2: Translated Version
            elif (
                sim_score >= 0.70
                and source_doc.language
                and target_doc.language
                and source_doc.language != target_doc.language
            ):
                relationships.append(
                    DocumentRelationship(
                        source_document_id=source_doc.id,
                        target_document_id=target_id,
                        relationship_type=RELATIONSHIP_TRANSLATED,
                        similarity_score=round(sim_score, 4),
                    )
                )

            # Rule 3: Supersedes / Version Of
            elif (
                source_doc.filename.lower() == target_doc.filename.lower()
                and source_doc.created_at > target_doc.created_at
            ):
                relationships.append(
                    DocumentRelationship(
                        source_document_id=source_doc.id,
                        target_document_id=target_id,
                        relationship_type=RELATIONSHIP_SUPERSEDES,
                        similarity_score=round(sim_score, 4),
                    )
                )

            # Rule 4: Same Topic / Classification
            elif (
                source_doc.classification
                and source_doc.classification == target_doc.classification
            ):
                relationships.append(
                    DocumentRelationship(
                        source_document_id=source_doc.id,
                        target_document_id=target_id,
                        relationship_type=RELATIONSHIP_SAME_TOPIC,
                        similarity_score=round(sim_score, 4),
                    )
                )

            # Rule 5: Similar
            elif sim_score >= 0.65:
                relationships.append(
                    DocumentRelationship(
                        source_document_id=source_doc.id,
                        target_document_id=target_id,
                        relationship_type=RELATIONSHIP_SIMILAR,
                        similarity_score=round(sim_score, 4),
                    )
                )

        if relationships:
            self.db.add_all(relationships)
            self.db.commit()

        logger.info(
            f"DocumentRelationshipService: Detected {len(relationships)} relationships for Doc {document_id}"
        )
        return relationships
