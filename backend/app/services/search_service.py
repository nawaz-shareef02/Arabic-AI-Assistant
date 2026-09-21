# pyrefly: ignore-file
"""
SearchService — Enterprise Hybrid Search.

Sprint 12 Extension:
- keyword_search()  — PostgreSQL Full-Text Search (GIN-indexed tsvector)
- hybrid_search()   — Dense + Keyword with Reciprocal Rank Fusion (RRF)
- semantic_search()  — preserved unchanged for backward compatibility

All retrieval logic lives here. No separate BM25 service.
Rank fusion (RRF) is internal to this service.
Metadata filtering is applied during retrieval (not post-hoc).

Architecture
------------
- Uses singleton EmbeddingService and QdrantService — no re-initialization.
- DB session passed at construction for PostgreSQL FTS queries.
- SearchResult dataclass provides a unified result format across
  dense and keyword retrieval sources.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.parsed_document import ParsedDocument
from app.services.embedding_service import EmbeddingService
from app.services.fts_normalizer import FTSStrategy, build_ts_query
from app.services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Unified Search Result
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """
    Unified search result from any retrieval source.

    Used by SearchService, RAGService, RerankerService, and RetrievalProfiler.
    Debug fields (vector_score, keyword_score, rrf_rank, etc.) are populated
    ONLY when ENABLE_RETRIEVAL_DEBUG is True.
    """

    chunk_id: int
    chunk_uuid: str
    parsed_document_id: int
    knowledge_base_id: int
    chunk_index: int
    text: str
    char_count: int
    estimated_tokens: int
    score: float
    # Debug & Intelligence metadata
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rrf_rank: Optional[int] = None
    document_id: Optional[int] = None
    document_name: Optional[str] = None
    language: Optional[str] = None
    classification: Optional[str] = None
    match_explanations: Optional[Dict[str, Any]] = None


# ──────────────────────────────────────────────────────────────────────────────
# Centralized Validation Helpers (AI-3 Hardening)
# ──────────────────────────────────────────────────────────────────────────────


def validate_top_k(top_k: Optional[int], default: int) -> int:
    """
    Centralized Top-K validation mechanism (Fix #4).

    Expected behavior:
    - None -> existing safe default
    - <= 0 -> existing safe default
    - 3 -> 3, 5 -> 5, 10 -> 10, 15 -> 15
    - 50000 -> 50 (bounded to RETRIEVAL_MAX_TOP_K)
    """
    if top_k is None or top_k <= 0:
        return default
    return min(top_k, settings.RETRIEVAL_MAX_TOP_K)


def validate_query(query: Optional[str]) -> str:
    """
    Centralized query length and validity safety mechanism (Fix #5).

    Rejects:
    - empty query
    - whitespace-only query
    - query > RETRIEVAL_MAX_QUERY_LENGTH (2000 characters)

    Preserves valid:
    - English, Arabic, bilingual, legal, enterprise queries without
      normalizing away meaningful Arabic/English content.
    """
    if query is None or not query.strip():
        raise ValueError("Query cannot be empty or whitespace-only.")
    if len(query) > settings.RETRIEVAL_MAX_QUERY_LENGTH:
        raise ValueError(
            f"Query length ({len(query)}) exceeds maximum allowed limit of "
            f"{settings.RETRIEVAL_MAX_QUERY_LENGTH} characters."
        )
    return query


def validate_tenant_boundaries(
    organization_id: Optional[int],
    knowledge_base_id: Optional[int],
) -> None:
    """
    Centralized tenant boundary validation mechanism (Fix #3).

    For normal authenticated user retrieval, both boundaries are mandatory:
    - organization_id
    - knowledge_base_id

    If either is missing, retrieval MUST fail closed immediately.
    """
    if organization_id is None or knowledge_base_id is None:
        raise ValueError(
            f"Tenant boundary missing: both 'organization_id' (got {organization_id}) and "
            f"'knowledge_base_id' (got {knowledge_base_id}) are mandatory for retrieval."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Search Service
# ──────────────────────────────────────────────────────────────────────────────


class SearchService:
    """
    Enterprise Search Service — Hybrid Dense + Keyword Retrieval.

    Uses singleton EmbeddingService and QdrantService so no heavy objects
    are re-instantiated per request.
    """

    def __init__(self, db: Session):
        self.db = db
        # Both constructors return singleton-backed instances — no re-initialization.
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    # ------------------------------------------------------------------
    # Existing: Semantic Search (backward compatible — Sprint ≤11)
    # ------------------------------------------------------------------

    def semantic_search(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        top_k: Optional[int] = None,
    ):
        """
        Original semantic search — returns raw Qdrant ScoredPoint objects with organization scoping.
        """
        query = validate_query(query)
        validate_tenant_boundaries(organization_id, knowledge_base_id)
        effective_top_k = validate_top_k(top_k, default=settings.TOP_K_RESULTS)

        results = self.qdrant_service.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            limit=effective_top_k,
        )

        return results

    # ------------------------------------------------------------------
    # Sprint 12: Keyword Search (PostgreSQL Full-Text Search)
    # ------------------------------------------------------------------

    def keyword_search(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        top_k: Optional[int] = None,
        language: Optional[str] = None,
        document_type: Optional[str] = None,
        document_id: Optional[int] = None,
        classification: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        PostgreSQL Full-Text Search on document_chunks.search_vector with organization defense-in-depth.

        Uses a GIN-indexed tsvector column for fast keyword retrieval.
        Enforces both organization_id and knowledge_base_id in a single indexed SQL query.
        Metadata filters (language, document_type, document_id, classification) are applied
        as SQL WHERE clauses during query execution — not post-hoc.
        """
        query = validate_query(query)
        validate_tenant_boundaries(organization_id, knowledge_base_id)
        effective_top_k = validate_top_k(top_k, default=settings.HYBRID_MAX_RESULTS)

        ts_query = func.plainto_tsquery("simple", query)
        rank = func.ts_rank(DocumentChunk.search_vector, ts_query)

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.uuid,
                DocumentChunk.parsed_document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.chunk_text,
                DocumentChunk.char_count,
                DocumentChunk.estimated_tokens,
                rank.label("rank"),
                Document.id.label("doc_id"),
                Document.filename.label("doc_name"),
                Document.language.label("doc_language"),
                Document.classification.label("doc_classification"),
                Document.knowledge_base_id,
            )
            .join(
                ParsedDocument,
                DocumentChunk.parsed_document_id == ParsedDocument.id,
            )
            .join(Document, ParsedDocument.document_id == Document.id)
            .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
            .where(KnowledgeBase.organization_id == organization_id)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .where(DocumentChunk.search_vector.op("@@")(ts_query))
        )

        # ── Metadata filtering during retrieval ──────────────────────────
        if settings.ENABLE_METADATA_FILTERING:
            if language:
                stmt = stmt.where(Document.language == language)
            if document_type:
                stmt = stmt.where(Document.mime_type == document_type)
            if document_id:
                stmt = stmt.where(Document.id == document_id)
            if classification:
                stmt = stmt.where(Document.classification == classification)

        stmt = stmt.order_by(rank.desc()).limit(effective_top_k)

        try:
            rows = self.db.execute(stmt).all()
        except Exception as exc:
            logger.warning(f"Keyword search failed: {exc}")
            return []

        debug = settings.ENABLE_RETRIEVAL_DEBUG
        results: List[SearchResult] = []
        for row in rows:
            results.append(
                SearchResult(
                    chunk_id=row.id,
                    chunk_uuid=str(row.uuid),
                    parsed_document_id=row.parsed_document_id,
                    knowledge_base_id=row.knowledge_base_id,
                    chunk_index=row.chunk_index,
                    text=row.chunk_text,
                    char_count=row.char_count,
                    estimated_tokens=row.estimated_tokens,
                    score=float(row.rank) if row.rank else 0.0,
                    keyword_score=(
                        float(row.rank) if row.rank and debug else None
                    ),
                    document_id=row.doc_id if debug else None,
                    document_name=row.doc_name if debug else None,
                    language=row.doc_language if debug else None,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Sprint 12: Hybrid Search (Dense + Keyword + RRF)
    # ------------------------------------------------------------------

    def hybrid_search(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        expanded_query: Optional[str] = None,
        top_k: Optional[int] = None,
        language: Optional[str] = None,
        document_type: Optional[str] = None,
        document_id: Optional[int] = None,
        classification: Optional[str] = None,
        explain: bool = False,
        profiler: Optional[object] = None,
    ) -> List[SearchResult]:
        query = validate_query(query)
        if expanded_query:
            expanded_query = validate_query(expanded_query)
        validate_tenant_boundaries(organization_id, knowledge_base_id)
        effective_top_k = validate_top_k(top_k, default=settings.HYBRID_MAX_RESULTS)

        kw_query = expanded_query if expanded_query else query
        p = profiler  # shorthand

        # ── 1. Keyword Search (PostgreSQL FTS — completes DB queries early) ───
        if p:
            p.start("keyword_search")
        keyword_results = self.keyword_search(
            query=kw_query,
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            top_k=effective_top_k,
            language=language,
            document_type=document_type,
            document_id=document_id,
            classification=classification,
        )
        if p:
            p.stop("keyword_search")
            p.set("keyword_results", len(keyword_results))

        # P2-2: Release DB connection prior to external Qdrant network call
        try:
            self.db.commit()
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass

        # ── 2. Dense Vector Search (Qdrant external network call) ────────────
        dense_results = self._dense_search(
            query, knowledge_base_id, effective_top_k, profiler=p, organization_id=organization_id
        )
        if p:
            p.set("dense_results", len(dense_results))

        # ── Reciprocal Rank Fusion ───────────────────────────────────────
        if p:
            p.start("fusion")
        fused = self._reciprocal_rank_fusion(dense_results, keyword_results)
        if p:
            p.stop("fusion")
            p.set("fused_results", len(fused))

        final = fused[:effective_top_k]
        if p:
            p.set("final_results", len(final))

        # ── Search Explanations & Debug ──────────────────────────────────
        if settings.ENABLE_RETRIEVAL_DEBUG or explain:
            for r in final:
                r.match_explanations = {
                    "semantic_match": r.vector_score is not None and r.vector_score > 0.3,
                    "keyword_match": r.keyword_score is not None and r.keyword_score > 0,
                    "metadata_match": bool(language or document_type or classification),
                    "topic_match": r.classification is not None,
                    "entity_match": False,
                    "classification_match": r.classification == classification if classification else True,
                }
            if settings.ENABLE_RETRIEVAL_DEBUG:
                logger.info(
                    f"Hybrid search: dense={len(dense_results)} "
                    f"keyword={len(keyword_results)} "
                    f"fused={len(fused)} final={len(final)}"
                )

        return final

    # --------------------------------------------------
    # Internal: Dense Search → SearchResult
    # --------------------------------------------------

    def _dense_search(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        top_k: Optional[int] = None,
        profiler: Optional[object] = None,
        organization_id: Optional[int] = None,
    ) -> List[SearchResult]:
        """Dense vector retrieval via Qdrant."""
        query = validate_query(query)
        validate_tenant_boundaries(organization_id, knowledge_base_id)
        effective_top_k = validate_top_k(top_k, default=settings.TOP_K_RESULTS)
        p = profiler

        # ── Embed query ──────────────────────────────────────────────────
        if p:
            p.start("embedding")
        query_vector = self.embedding_service.embed_text(query)
        if p:
            p.stop("embedding")

        # ── Qdrant query ─────────────────────────────────────────────────
        if p:
            p.start("dense_search")
        try:
            qdrant_results = self.qdrant_service.search(
                query_vector=query_vector,
                knowledge_base_id=knowledge_base_id,
                organization_id=organization_id,
                limit=effective_top_k,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.warning(f"Dense vector Qdrant search failed (degrading to keyword search): {exc}")
            qdrant_results = []
        if p:
            p.stop("dense_search")

        # ── Convert to SearchResult ──────────────────────────────────────
        debug = settings.ENABLE_RETRIEVAL_DEBUG
        results: List[SearchResult] = []
        for item in qdrant_results:
            results.append(
                SearchResult(
                    chunk_id=item.id,
                    chunk_uuid=item.payload.get("chunk_uuid", ""),
                    parsed_document_id=item.payload.get(
                        "parsed_document_id", 0
                    ),
                    knowledge_base_id=item.payload.get(
                        "knowledge_base_id", 0
                    ),
                    chunk_index=item.payload.get("chunk_index", 0),
                    text=item.payload.get("text", ""),
                    char_count=item.payload.get("char_count", 0),
                    estimated_tokens=item.payload.get("estimated_tokens", 0),
                    score=float(item.score),
                    vector_score=float(item.score) if debug else None,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Internal: Reciprocal Rank Fusion (RRF)
    # ------------------------------------------------------------------

    def _reciprocal_rank_fusion(
        self,
        dense_results: List[SearchResult],
        keyword_results: List[SearchResult],
    ) -> List[SearchResult]:
        """
        Reciprocal Rank Fusion (RRF).

        score(d) = Σ 1 / (k + rank_i)  for each ranking that contains d.

        k = settings.RRF_K (default 60).
        Deduplicates by chunk_uuid. Merges scores from both sources.
        """
        k = settings.RRF_K
        scores: Dict[str, float] = {}
        result_map: Dict[str, SearchResult] = {}
        debug = settings.ENABLE_RETRIEVAL_DEBUG

        # ── Accumulate from dense ranking ────────────────────────────────
        for rank, result in enumerate(dense_results, start=1):
            key = result.chunk_uuid
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in result_map:
                result_map[key] = result
            if debug:
                result_map[key].vector_score = result.score

        # ── Accumulate from keyword ranking ──────────────────────────────
        for rank, result in enumerate(keyword_results, start=1):
            key = result.chunk_uuid
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in result_map:
                result_map[key] = result
            if debug:
                result_map[key].keyword_score = result.score

        # ── Sort by RRF score descending ─────────────────────────────────
        sorted_keys = sorted(
            scores.keys(), key=lambda x: scores[x], reverse=True
        )

        fused: List[SearchResult] = []
        for rank, key in enumerate(sorted_keys, start=1):
            result = result_map[key]
            result.score = scores[key]
            if debug:
                result.rrf_rank = rank
            fused.append(result)

        return fused

    # ------------------------------------------------------------------
    # AI-3B.1 Experimentation Only: Internal Keyword Search
    # ------------------------------------------------------------------

    def _keyword_search_experimental(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        strategy: FTSStrategy = FTSStrategy.BASELINE,
        top_k: Optional[int] = None,
        language: Optional[str] = None,
        document_type: Optional[str] = None,
        document_id: Optional[int] = None,
        classification: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        PostgreSQL Full-Text Search with experimental query formulation strategies.

        EXPERIMENT / BENCHMARK ONLY — Completely unreachable from production paths.
        Enforces both organization_id and knowledge_base_id in a single indexed SQL query.
        """
        query = validate_query(query)
        validate_tenant_boundaries(organization_id, knowledge_base_id)
        effective_top_k = validate_top_k(top_k, default=settings.HYBRID_MAX_RESULTS)

        ts_query = build_ts_query(query, strategy)
        rank = func.ts_rank(DocumentChunk.search_vector, ts_query)

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.uuid,
                DocumentChunk.parsed_document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.chunk_text,
                DocumentChunk.char_count,
                DocumentChunk.estimated_tokens,
                rank.label("rank"),
                Document.id.label("doc_id"),
                Document.filename.label("doc_name"),
                Document.language.label("doc_language"),
                Document.classification.label("doc_classification"),
                Document.knowledge_base_id,
            )
            .join(
                ParsedDocument,
                DocumentChunk.parsed_document_id == ParsedDocument.id,
            )
            .join(Document, ParsedDocument.document_id == Document.id)
            .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
            .where(KnowledgeBase.organization_id == organization_id)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .where(DocumentChunk.search_vector.op("@@")(ts_query))
        )

        # ── Metadata filtering during retrieval ──────────────────────────
        if settings.ENABLE_METADATA_FILTERING:
            if language:
                stmt = stmt.where(Document.language == language)
            if document_type:
                stmt = stmt.where(Document.mime_type == document_type)
            if document_id:
                stmt = stmt.where(Document.id == document_id)
            if classification:
                stmt = stmt.where(Document.classification == classification)

        stmt = stmt.order_by(rank.desc()).limit(effective_top_k)

        try:
            rows = self.db.execute(stmt).all()
        except Exception as exc:
            logger.warning(f"Experimental keyword search failed: {exc}")
            return []

        debug = settings.ENABLE_RETRIEVAL_DEBUG
        results: List[SearchResult] = []
        for row in rows:
            results.append(
                SearchResult(
                    chunk_id=row.id,
                    chunk_uuid=str(row.uuid),
                    parsed_document_id=row.parsed_document_id,
                    knowledge_base_id=row.knowledge_base_id,
                    chunk_index=row.chunk_index,
                    text=row.chunk_text,
                    char_count=row.char_count,
                    estimated_tokens=row.estimated_tokens,
                    score=float(row.rank) if row.rank else 0.0,
                    keyword_score=(
                        float(row.rank) if row.rank and debug else None
                    ),
                    document_id=row.doc_id if debug else None,
                    document_name=row.doc_name if debug else None,
                    language=row.doc_language if debug else None,
                )
            )

        return results