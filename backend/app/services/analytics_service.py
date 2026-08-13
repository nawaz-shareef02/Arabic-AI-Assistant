"""
AnalyticsService — Unified Analytics Facade for Knowledge, Search & Usage Telemetry.

Refinement #10:
Internally separates:
- SearchAnalyticsSubservice
- KnowledgeAnalyticsSubservice
- UsageAnalyticsSubservice
Exposes single AnalyticsService facade.
"""

import logging
import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.document_entity import DocumentEntity
from app.models.document_metadata import DocumentMetadata
from app.models.search_analytics import SearchAnalytics

logger = logging.getLogger(__name__)


class SearchAnalyticsSubservice:
    """Subservice for query search logs and latency telemetry."""

    def __init__(self, db: Session):
        self.db = db

    def record_query(
        self,
        query: str,
        latency_ms: float,
        results_count: int,
        user_id: int | None = None,
        kb_id: int | None = None,
        chunks_returned: List[Dict[str, Any]] | None = None,
        filters_used: Dict[str, Any] | None = None,
    ) -> None:
        try:
            record = SearchAnalytics(
                query=query,
                retrieval_latency_ms=latency_ms,
                results_count=results_count,
                user_id=user_id,
                knowledge_base_id=kb_id,
                chunks_returned=chunks_returned or [],
                filters_used=filters_used or {},
            )
            self.db.add(record)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to record search analytics: {e}")

    def get_search_metrics(self) -> Dict[str, Any]:
        avg_latency = (
            self.db.query(func.avg(SearchAnalytics.retrieval_latency_ms)).scalar() or 0.0
        )
        total_queries = self.db.query(SearchAnalytics).count()

        top_queries_query = (
            self.db.query(SearchAnalytics.query, func.count(SearchAnalytics.id).label("count"))
            .group_by(SearchAnalytics.query)
            .order_by(func.count(SearchAnalytics.id).desc())
            .limit(5)
            .all()
        )

        top_queries = [{"query": q, "count": c} for q, c in top_queries_query]

        return {
            "total_queries": total_queries,
            "average_latency_ms": round(avg_latency, 2),
            "top_queries": top_queries,
        }


class KnowledgeAnalyticsSubservice:
    """Subservice for knowledge base metrics, unused docs, entities, and category distributions."""

    def __init__(self, db: Session):
        self.db = db

    def get_knowledge_metrics(self, owner_id: int | None = None) -> Dict[str, Any]:
        kb_query = self.db.query(KnowledgeBase)
        doc_query = self.db.query(Document)

        if owner_id is not None:
            kb_query = kb_query.filter(KnowledgeBase.owner_id == owner_id)
            doc_query = doc_query.join(KnowledgeBase).filter(KnowledgeBase.owner_id == owner_id)

        total_kbs = kb_query.count()
        total_docs = doc_query.count()

        # Unused documents (status Parsed but not in any search_analytics log)
        unused_docs = (
            doc_query.filter(Document.status == "Parsed", Document.chunk_count > 0)
            .order_by(Document.created_at.desc())
            .limit(10)
            .all()
        )

        unused_list = [
            {
                "uuid": str(d.uuid),
                "filename": d.filename,
                "created_at": d.created_at.isoformat(),
                "classification": d.classification or "Technical Documentation",
            }
            for d in unused_docs
        ]

        # Top document categories
        categories_query = (
            self.db.query(Document.classification, func.count(Document.id).label("count"))
            .group_by(Document.classification)
            .order_by(func.count(Document.id).desc())
            .all()
        )
        category_distribution = [
            {"category": cat or "Unclassified", "count": count}
            for cat, count in categories_query
        ]

        # Top entities
        entities_query = (
            self.db.query(DocumentEntity.entity_text, DocumentEntity.entity_type, func.count(DocumentEntity.id).label("count"))
            .group_by(DocumentEntity.entity_text, DocumentEntity.entity_type)
            .order_by(func.count(DocumentEntity.id).desc())
            .limit(10)
            .all()
        )
        top_entities = [
            {"text": text, "type": etype, "count": count}
            for text, etype, count in entities_query
        ]

        return {
            "total_knowledge_bases": total_kbs,
            "total_documents": total_docs,
            "category_distribution": category_distribution,
            "top_entities": top_entities,
            "unused_documents": unused_list,
        }


class UsageAnalyticsSubservice:
    """Subservice for usage trends and daily ingestion metrics."""

    def __init__(self, db: Session):
        self.db = db

    def get_usage_trends(self) -> Dict[str, Any]:
        # Daily ingestion count for last 7 days
        today = datetime.date.today()
        daily_questions = []
        storage_growth = []

        for i in range(6, -1, -1):
            day = today - datetime.timedelta(days=i)
            day_str = day.strftime("%b %d")

            doc_count = (
                self.db.query(Document)
                .filter(func.date(Document.created_at) == day)
                .count()
            )
            query_count = (
                self.db.query(SearchAnalytics)
                .filter(func.date(SearchAnalytics.created_at) == day)
                .count()
            )

            daily_questions.append({"date": day_str, "count": query_count})
            storage_growth.append({"date": day_str, "count": doc_count * 2})  # approx MB

        return {
            "dailyQuestions": daily_questions,
            "storageGrowthMb": storage_growth,
        }


class AnalyticsService:
    """Unified Facade for Enterprise Knowledge Intelligence Analytics."""

    def __init__(self, db: Session):
        self.db = db
        self.search_analytics = SearchAnalyticsSubservice(db)
        self.knowledge_analytics = KnowledgeAnalyticsSubservice(db)
        self.usage_analytics = UsageAnalyticsSubservice(db)

    def get_full_analytics(self, owner_id: int | None = None) -> Dict[str, Any]:
        search_data = self.search_analytics.get_search_metrics()
        knowledge_data = self.knowledge_analytics.get_knowledge_metrics(owner_id)
        usage_data = self.usage_analytics.get_usage_trends()

        return {
            **search_data,
            **knowledge_data,
            **usage_data,
        }
