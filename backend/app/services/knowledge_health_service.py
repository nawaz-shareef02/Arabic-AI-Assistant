"""
KnowledgeHealthService — Weighted Multi-Dimensional Knowledge Base Health Scoring.

Refinement #7:
Health score composed of multiple weighted dimensions:
1. Metadata Completeness (Weight: 0.15)
2. Embedding Coverage (Weight: 0.20)
3. OCR / Parsing Quality (Weight: 0.15)
4. Relationship Coverage (Weight: 0.10)
5. Duplicate Detection Penalty (Weight: 0.10)
6. Freshness (Weight: 0.10)
7. Classification Coverage (Weight: 0.10)
8. Entity Coverage (Weight: 0.10)

Calculates an overall percentage score (0-100%) and itemizes health issues.
"""

import logging
import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.document import Document
from app.models.document_metadata import DocumentMetadata
from app.models.document_entity import DocumentEntity
from app.models.document_relationship import DocumentRelationship

logger = logging.getLogger(__name__)


class KnowledgeHealthService:
    def __init__(self, db: Session):
        self.db = db

    def calculate_health(self, knowledge_base_id: int | None = None) -> Dict[str, Any]:
        query = self.db.query(Document)
        if knowledge_base_id is not None:
            query = query.filter(Document.knowledge_base_id == knowledge_base_id)

        docs = query.all()
        total_docs = len(docs)

        if total_docs == 0:
            return {
                "score": 100.0,
                "status": "Healthy",
                "total_documents": 0,
                "dimensions": {},
                "issues": [],
            }

        issues: List[Dict[str, Any]] = []

        # 1. Metadata Completeness
        metadata_count = (
            self.db.query(DocumentMetadata)
            .filter(DocumentMetadata.document_id.in_([d.id for d in docs]))
            .count()
        )
        meta_score = (metadata_count / total_docs) * 100.0
        if meta_score < 100:
            issues.append({
                "type": "Missing Metadata",
                "severity": "Medium",
                "message": f"{total_docs - metadata_count} documents are missing enriched metadata.",
            })

        # 2. Embedding Coverage
        embedded_docs = [d for d in docs if d.status == "Parsed" and d.chunk_count > 0]
        emb_score = (len(embedded_docs) / total_docs) * 100.0
        if emb_score < 100:
            issues.append({
                "type": "Missing Embeddings",
                "severity": "High",
                "message": f"{total_docs - len(embedded_docs)} documents do not have indexed chunk embeddings.",
            })

        # 3. OCR / Parsing Quality (Char count > 50)
        good_parsing = [
            d for d in docs if d.parsed_document and d.parsed_document.char_count > 50
        ]
        ocr_score = (len(good_parsing) / total_docs) * 100.0
        if ocr_score < 100:
            issues.append({
                "type": "Low Quality / Small File",
                "severity": "Medium",
                "message": f"{total_docs - len(good_parsing)} documents have very low character counts or small payloads.",
            })

        # 4. Relationship Coverage
        rel_doc_ids = set(
            r.source_document_id
            for r in self.db.query(DocumentRelationship)
            .filter(DocumentRelationship.source_document_id.in_([d.id for d in docs]))
            .all()
        )
        rel_score = (len(rel_doc_ids) / total_docs) * 100.0 if total_docs > 1 else 100.0

        # 5. Duplicate Detection (Percentage of NON-duplicate documents)
        duplicates = (
            self.db.query(DocumentRelationship)
            .filter(
                DocumentRelationship.source_document_id.in_([d.id for d in docs]),
                DocumentRelationship.relationship_type == "Duplicate",
            )
            .count()
        )
        dup_score = max(0.0, 100.0 - (duplicates / total_docs) * 100.0)
        if duplicates > 0:
            issues.append({
                "type": "Duplicate Documents",
                "severity": "High",
                "message": f"Detected {duplicates} duplicate document relationship pairs.",
            })

        # 6. Freshness (Documents updated in last 90 days)
        now = datetime.datetime.now(datetime.timezone.utc)
        ninety_days_ago = now - datetime.timedelta(days=90)
        fresh_docs = [d for d in docs if d.created_at >= ninety_days_ago]
        fresh_score = (len(fresh_docs) / total_docs) * 100.0

        # 7. Classification Coverage
        classified_docs = [d for d in docs if d.classification and d.classification != "Unclassified"]
        class_score = (len(classified_docs) / total_docs) * 100.0

        # 8. Entity Coverage
        ent_doc_ids = set(
            e.document_id
            for e in self.db.query(DocumentEntity)
            .filter(DocumentEntity.document_id.in_([d.id for d in docs]))
            .all()
        )
        ent_score = (len(ent_doc_ids) / total_docs) * 100.0

        # Compute weighted score
        final_score = (
            meta_score * 0.15
            + emb_score * 0.20
            + ocr_score * 0.15
            + rel_score * 0.10
            + dup_score * 0.10
            + fresh_score * 0.10
            + class_score * 0.10
            + ent_score * 0.10
        )

        status_label = (
            "Optimal"
            if final_score >= 90
            else "Healthy"
            if final_score >= 75
            else "Needs Attention"
            if final_score >= 50
            else "Critical"
        )

        return {
            "score": round(final_score, 1),
            "status": status_label,
            "total_documents": total_docs,
            "dimensions": {
                "metadata_completeness": round(meta_score, 1),
                "embedding_coverage": round(emb_score, 1),
                "ocr_quality": round(ocr_score, 1),
                "relationship_coverage": round(rel_score, 1),
                "duplicate_score": round(dup_score, 1),
                "freshness": round(fresh_score, 1),
                "classification_coverage": round(class_score, 1),
                "entity_coverage": round(ent_score, 1),
            },
            "issues": issues,
        }
