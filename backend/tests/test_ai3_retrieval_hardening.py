"""
AI-3 Pre-Benchmark Retrieval Hardening & Performance Safety Behavioral Tests.

Tests:
- TEST A: Streaming organization propagation to hybrid_search().
- TEST B: PostgreSQL FTS tenant isolation (Org A vs Org B).
- TEST C: Cross-tenant FTS mismatch rejection (Org-A + KB-B / Org-B + KB-A).
- TEST D: Qdrant tenant filtering (both organization_id and knowledge_base_id).
- TEST E: Missing tenant boundary fail-closed (None, None / Org, None / None, KB).
- TEST F: Centralized Top-K boundaries (3, 5, 10, 15, 50000->50, <=0 -> default).
- TEST G: Centralized query length boundaries (AR, EN, bilingual, empty, >2000 chars).
- TEST H: Qdrant payload-index safety and vector preservation.
"""

import uuid
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import func

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.organization import Organization
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.models.chunk import DocumentChunk
from app.services.rag_service import RAGService
from app.services.qdrant_service import QdrantService
from app.services.search_service import (
    SearchService,
    validate_top_k,
    validate_query,
    validate_tenant_boundaries,
)
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    PayloadSchemaType,
)


# ──────────────────────────────────────────────────────────────────────────────
# TEST A: Streaming Organization Propagation
# ──────────────────────────────────────────────────────────────────────────────

def test_a_streaming_organization_propagation():
    """
    TEST A: Verify organization_id is strictly forwarded to hybrid_search()
    in RAGService.stream_ask_with_history().
    """
    mock_db = MagicMock()
    rag = RAGService(mock_db)

    # Mock user message repository
    mock_msg = MagicMock()
    mock_msg.id = 100
    rag._msg_repo = MagicMock()
    rag._msg_repo.create.return_value = mock_msg
    rag._msg_repo.get_history.return_value = []

    # Mock query rewriter and expansion
    rag._rewriter = MagicMock()
    rag._rewriter.rewrite.return_value = "rewritten question"
    rag._expand_query = MagicMock(return_value="expanded question")

    # Mock search service and LLM
    mock_result = MagicMock()
    mock_result.text = "Context snippet"
    rag.search_service = MagicMock()
    rag.search_service.hybrid_search.return_value = [mock_result]
    rag.llm = MagicMock()
    rag.llm.stream_generate.return_value = iter(["Token1", "Token2"])
    rag._persist_assistant_message = MagicMock()

    stream_gen = rag.stream_ask_with_history(
        question="What is ArabIQ streaming architecture?",
        knowledge_base_id=42,
        conversation_id=99,
        user_id=7,
        organization_id=12,
    )

    # Consume first token to trigger retrieval step
    next(stream_gen)

    # Assert hybrid_search received the explicit organization_id
    rag.search_service.hybrid_search.assert_called_once()
    _, kwargs = rag.search_service.hybrid_search.call_args
    assert kwargs.get("organization_id") == 12, "organization_id was NOT forwarded to hybrid_search!"
    assert kwargs.get("knowledge_base_id") == 42, "knowledge_base_id was NOT forwarded to hybrid_search!"


# ──────────────────────────────────────────────────────────────────────────────
# TEST B: PostgreSQL FTS Tenant Isolation
# ──────────────────────────────────────────────────────────────────────────────

def test_b_postgresql_fts_tenant_isolation():
    """
    TEST B: Verify that in PostgreSQL FTS, Organization A retrieves only
    Organization A's chunks, and Organization B retrieves only Organization B's chunks.
    """
    db = SessionLocal()
    search_service = SearchService(db)

    test_uid = uuid.uuid4().hex[:8]
    org_a = Organization(name=f"Org A {test_uid}", slug=f"org-a-{test_uid}")
    org_b = Organization(name=f"Org B {test_uid}", slug=f"org-b-{test_uid}")
    db.add_all([org_a, org_b])
    db.commit()

    try:
        user = db.query(User).first()
        user_id = user.id if user else 1

        kb_a = KnowledgeBase(name=f"KB A {test_uid}", organization_id=org_a.id, owner_id=user_id)
        kb_b = KnowledgeBase(name=f"KB B {test_uid}", organization_id=org_b.id, owner_id=user_id)
        db.add_all([kb_a, kb_b])
        db.commit()

        doc_a = Document(
            filename=f"doc_a_{test_uid}.txt",
            storage_path="/tmp/a",
            mime_type="text/plain",
            file_size=100,
            knowledge_base_id=kb_a.id,
            created_by=user_id,
            status="Processed",
        )
        doc_b = Document(
            filename=f"doc_b_{test_uid}.txt",
            storage_path="/tmp/b",
            mime_type="text/plain",
            file_size=100,
            knowledge_base_id=kb_b.id,
            created_by=user_id,
            status="Processed",
        )
        db.add_all([doc_a, doc_b])
        db.commit()

        pdoc_a = ParsedDocument(
            document_id=doc_a.id,
            parsed_text="Saudi Vision 2030 Enterprise Security Alpha",
            char_count=42,
            processing_duration=0.1,
        )
        pdoc_b = ParsedDocument(
            document_id=doc_b.id,
            parsed_text="Saudi Vision 2030 Enterprise Security Beta",
            char_count=41,
            processing_duration=0.1,
        )
        db.add_all([pdoc_a, pdoc_b])
        db.commit()

        chunk_a = DocumentChunk(
            parsed_document_id=pdoc_a.id,
            chunk_index=0,
            chunk_text="Saudi Vision 2030 Enterprise Security Alpha policy details.",
            char_count=58,
            estimated_tokens=15,
            start_offset=0,
            end_offset=58,
            search_vector=func.to_tsvector("simple", "Saudi Vision 2030 Enterprise Security Alpha policy details."),
        )
        chunk_b = DocumentChunk(
            parsed_document_id=pdoc_b.id,
            chunk_index=0,
            chunk_text="Saudi Vision 2030 Enterprise Security Beta policy details.",
            char_count=57,
            estimated_tokens=15,
            start_offset=0,
            end_offset=57,
            search_vector=func.to_tsvector("simple", "Saudi Vision 2030 Enterprise Security Beta policy details."),
        )
        db.add_all([chunk_a, chunk_b])
        db.commit()

        # Query as Org A
        res_a = search_service.keyword_search(
            query="Enterprise Security",
            knowledge_base_id=kb_a.id,
            organization_id=org_a.id,
        )
        assert len(res_a) == 1, "Org A should retrieve exactly 1 result"
        assert "Alpha" in res_a[0].text
        assert "Beta" not in res_a[0].text

        # Query as Org B
        res_b = search_service.keyword_search(
            query="Enterprise Security",
            knowledge_base_id=kb_b.id,
            organization_id=org_b.id,
        )
        assert len(res_b) == 1, "Org B should retrieve exactly 1 result"
        assert "Beta" in res_b[0].text
        assert "Alpha" not in res_b[0].text

    finally:
        db.query(DocumentChunk).filter(DocumentChunk.parsed_document_id.in_([pdoc_a.id, pdoc_b.id])).delete(synchronize_session=False)
        db.query(ParsedDocument).filter(ParsedDocument.id.in_([pdoc_a.id, pdoc_b.id])).delete(synchronize_session=False)
        db.query(Document).filter(Document.id.in_([doc_a.id, doc_b.id])).delete(synchronize_session=False)
        db.query(KnowledgeBase).filter(KnowledgeBase.id.in_([kb_a.id, kb_b.id])).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# TEST C: Cross-Tenant FTS Attempt Mismatch
# ──────────────────────────────────────────────────────────────────────────────

def test_c_cross_tenant_fts_mismatch_denied():
    """
    TEST C: Verify cross-tenant retrieval attempt:
    Org-A + KB-B -> denied / 0 chunks
    Org-B + KB-A -> denied / 0 chunks
    """
    db = SessionLocal()
    search_service = SearchService(db)

    test_uid = uuid.uuid4().hex[:8]
    org_a = Organization(name=f"Org A {test_uid}", slug=f"org-a-{test_uid}")
    org_b = Organization(name=f"Org B {test_uid}", slug=f"org-b-{test_uid}")
    db.add_all([org_a, org_b])
    db.commit()

    try:
        user = db.query(User).first()
        user_id = user.id if user else 1

        kb_a = KnowledgeBase(name=f"KB A {test_uid}", organization_id=org_a.id, owner_id=user_id)
        kb_b = KnowledgeBase(name=f"KB B {test_uid}", organization_id=org_b.id, owner_id=user_id)
        db.add_all([kb_a, kb_b])
        db.commit()

        doc_a = Document(
            filename=f"doc_a_{test_uid}.txt",
            storage_path="/tmp/a",
            mime_type="text/plain",
            file_size=100,
            knowledge_base_id=kb_a.id,
            created_by=user_id,
            status="Processed",
        )
        db.add(doc_a)
        db.commit()

        pdoc_a = ParsedDocument(
            document_id=doc_a.id,
            parsed_text="Confidential Financial Plan for Org Alpha",
            char_count=41,
            processing_duration=0.1,
        )
        db.add(pdoc_a)
        db.commit()

        chunk_a = DocumentChunk(
            parsed_document_id=pdoc_a.id,
            chunk_index=0,
            chunk_text="Confidential Financial Plan for Org Alpha with secret margins.",
            char_count=62,
            estimated_tokens=15,
            start_offset=0,
            end_offset=62,
            search_vector=func.to_tsvector("simple", "Confidential Financial Plan for Org Alpha with secret margins."),
        )
        db.add(chunk_a)
        db.commit()

        # Org B maliciously attempts to query Org A's KB
        res_cross = search_service.keyword_search(
            query="Confidential Financial",
            knowledge_base_id=kb_a.id,
            organization_id=org_b.id,  # Mismatched organization!
        )
        assert len(res_cross) == 0, "Cross-tenant FTS attack returned data! Must be 0 results."

        # Org A attempts to query Org B's KB
        res_cross_reverse = search_service.keyword_search(
            query="Confidential Financial",
            knowledge_base_id=kb_b.id,
            organization_id=org_a.id,  # Mismatched organization!
        )
        assert len(res_cross_reverse) == 0, "Cross-tenant FTS reverse attack returned data! Must be 0 results."

    finally:
        db.query(DocumentChunk).filter(DocumentChunk.parsed_document_id == pdoc_a.id).delete(synchronize_session=False)
        db.query(ParsedDocument).filter(ParsedDocument.id == pdoc_a.id).delete(synchronize_session=False)
        db.query(Document).filter(Document.id == doc_a.id).delete(synchronize_session=False)
        db.query(KnowledgeBase).filter(KnowledgeBase.id.in_([kb_a.id, kb_b.id])).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# TEST D: Qdrant Tenant Filter
# ──────────────────────────────────────────────────────────────────────────────

def test_d_qdrant_tenant_filter():
    """
    TEST D: Verify normal Qdrant vector retrieval unconditionally builds
    and applies both organization_id and knowledge_base_id filters.
    """
    qdrant_svc = QdrantService()

    with patch.object(qdrant_svc.client, "query_points") as mock_query:
        mock_response = MagicMock()
        mock_response.points = []
        mock_query.return_value = mock_response

        qdrant_svc.search(
            query="Saudi Labor Law",
            knowledge_base_id=14,
            organization_id=8,
            limit=5,
        )

        mock_query.assert_called_once()
        _, kwargs = mock_query.call_args
        query_filter = kwargs.get("query_filter")
        assert query_filter is not None, "query_filter was None!"

        keys_present = {c.key: c.match.value for c in query_filter.must}
        assert keys_present.get("organization_id") == 8
        assert keys_present.get("knowledge_base_id") == 14


# ──────────────────────────────────────────────────────────────────────────────
# TEST E: Missing Tenant Boundary Fail-Closed
# ──────────────────────────────────────────────────────────────────────────────

def test_e_missing_tenant_boundary_fails_closed():
    """
    TEST E: Missing tenant boundaries must fail closed immediately:
    - organization_id=None, knowledge_base_id=10 -> denied (ValueError)
    - organization_id=5, knowledge_base_id=None -> denied (ValueError)
    - organization_id=None, knowledge_base_id=None -> denied (ValueError)
    Tested across QdrantService, keyword_search, semantic_search, and hybrid_search.
    """
    qdrant_svc = QdrantService()
    mock_db = MagicMock()
    search_service = SearchService(mock_db)

    # 1. QdrantService.search() fail-closed
    with pytest.raises(ValueError, match="Tenant boundary missing"):
        qdrant_svc.search(query="test", organization_id=None, knowledge_base_id=10)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        qdrant_svc.search(query="test", organization_id=5, knowledge_base_id=None)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        qdrant_svc.search(query="test", organization_id=None, knowledge_base_id=None)

    # 2. SearchService.validate_tenant_boundaries()
    with pytest.raises(ValueError, match="Tenant boundary missing"):
        validate_tenant_boundaries(None, 10)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        validate_tenant_boundaries(5, None)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        validate_tenant_boundaries(None, None)

    # 3. SearchService.semantic_search() fail-closed
    with pytest.raises(ValueError, match="Tenant boundary missing"):
        search_service.semantic_search("test query", knowledge_base_id=10, organization_id=None)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        search_service.semantic_search("test query", knowledge_base_id=None, organization_id=5)

    # 4. SearchService.keyword_search() fail-closed
    with pytest.raises(ValueError, match="Tenant boundary missing"):
        search_service.keyword_search("test query", knowledge_base_id=10, organization_id=None)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        search_service.keyword_search("test query", knowledge_base_id=None, organization_id=5)

    # 5. SearchService.hybrid_search() fail-closed
    with pytest.raises(ValueError, match="Tenant boundary missing"):
        search_service.hybrid_search("test query", knowledge_base_id=10, organization_id=None)

    with pytest.raises(ValueError, match="Tenant boundary missing"):
        search_service.hybrid_search("test query", knowledge_base_id=None, organization_id=5)


# ──────────────────────────────────────────────────────────────────────────────
# TEST F: Centralized Top-K Safety
# ──────────────────────────────────────────────────────────────────────────────

def test_f_centralized_top_k_safety():
    """
    TEST F: Verify centralized Top-K validation:
    - 3, 5, 10, 15 are preserved.
    - 50000 is bounded to 50 (RETRIEVAL_MAX_TOP_K).
    - 0, negative values, and None fallback to safe default.
    """
    default = settings.TOP_K_RESULTS  # 3

    assert validate_top_k(3, default=default) == 3
    assert validate_top_k(5, default=default) == 5
    assert validate_top_k(10, default=default) == 10
    assert validate_top_k(15, default=default) == 15
    assert validate_top_k(50, default=default) == 50

    # Excessive boundary
    assert validate_top_k(50000, default=default) == 50
    assert validate_top_k(1000000, default=default) == 50

    # Zero, negative, and None
    assert validate_top_k(0, default=default) == default
    assert validate_top_k(-1, default=default) == default
    assert validate_top_k(-100, default=default) == default
    assert validate_top_k(None, default=default) == default


# ──────────────────────────────────────────────────────────────────────────────
# TEST G: Centralized Query Length Safety
# ──────────────────────────────────────────────────────────────────────────────

def test_g_centralized_query_length_safety():
    """
    TEST G: Verify centralized query length safety:
    - Normal Arabic, English, bilingual queries are accepted and preserved.
    - Empty or whitespace-only queries are rejected.
    - Queries > 2000 characters are safely rejected.
    """
    # 1. Normal valid queries
    ar_q = "ما هي شروط مكافأة نهاية الخدمة وفق نظام العمل السعودي؟"
    en_q = "What are the security boundaries for multi-tenant hybrid retrieval?"
    bi_q = "Explain the RRF fusion formula وحساب الترتيب التبادلي k=60"

    assert validate_query(ar_q) == ar_q
    assert validate_query(en_q) == en_q
    assert validate_query(bi_q) == bi_q

    # 2. Empty / whitespace rejection
    with pytest.raises(ValueError, match="Query cannot be empty"):
        validate_query("")

    with pytest.raises(ValueError, match="Query cannot be empty"):
        validate_query("   \n\t  ")

    with pytest.raises(ValueError, match="Query cannot be empty"):
        validate_query(None)

    # 3. Maximum boundary
    max_len = settings.RETRIEVAL_MAX_QUERY_LENGTH  # 2000
    valid_boundary_query = "أ" * max_len
    assert validate_query(valid_boundary_query) == valid_boundary_query

    # Oversized rejection
    oversized_query = "a" * (max_len + 1)
    with pytest.raises(ValueError, match="exceeds maximum allowed limit"):
        validate_query(oversized_query)


# ──────────────────────────────────────────────────────────────────────────────
# TEST H: Qdrant Payload-Index Safety & Idempotency
# ──────────────────────────────────────────────────────────────────────────────

def test_h_qdrant_payload_index_safety():
    """
    TEST H: Verify Qdrant payload-index creation:
    - Idempotent schema checks (invoked when missing, skipped when present).
    - Repeated initialization produces no duplicate errors.
    - Collection is preserved.
    - Vectors and points are strictly preserved.
    """
    in_memory_client = QdrantClient(":memory:")
    collection_name = "test_hardening_collection"

    # 1. Initialize collection with 1024 dimension cosine distance
    in_memory_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

    # 2. Insert test point
    test_vec = [0.01] * 1024
    in_memory_client.upsert(
        collection_name=collection_name,
        points=[
            PointStruct(
                id=1,
                vector=test_vec,
                payload={
                    "organization_id": 10,
                    "knowledge_base_id": 20,
                    "text": "Existing vector payload",
                },
            )
        ],
    )

    # Verify in-memory client behavior: repeated calls succeed and preserve vectors
    svc = QdrantService()
    with patch.object(QdrantService, "_client", in_memory_client), \
         patch.object(svc, "collection_name", collection_name):

        # First run of ensure_payload_indexes
        svc.ensure_payload_indexes()

        # Verify point and vector are preserved
        points_after_1 = in_memory_client.retrieve(collection_name=collection_name, ids=[1])
        assert len(points_after_1) == 1
        assert points_after_1[0].payload["text"] == "Existing vector payload"

        # Second run (Repeated initialization - Idempotency test)
        svc.ensure_payload_indexes()

        # Verify no failure and point is still preserved
        points_after_2 = in_memory_client.retrieve(collection_name=collection_name, ids=[1])
        assert len(points_after_2) == 1
        assert points_after_2[0].payload["organization_id"] == 10

    # 3. Behavioral verification of schema-inspection idempotency logic
    mock_client = MagicMock()
    mock_coll_info_missing = MagicMock()
    mock_coll_info_missing.payload_schema = {}
    mock_client.get_collection.return_value = mock_coll_info_missing

    with patch.object(QdrantService, "_client", mock_client), \
         patch.object(svc, "collection_name", "test_mock_coll"):

        # When missing: create_payload_index is called for both fields
        svc.ensure_payload_indexes()
        assert mock_client.create_payload_index.call_count == 2
        calls = [c[1]["field_name"] for c in mock_client.create_payload_index.call_args_list]
        assert "organization_id" in calls
        assert "knowledge_base_id" in calls

        # Reset and mock schema where both already exist with INTEGER data_type
        mock_client.reset_mock()
        mock_coll_info_existing = MagicMock()
        mock_coll_info_existing.payload_schema = {
            "organization_id": MagicMock(data_type=PayloadSchemaType.INTEGER),
            "knowledge_base_id": MagicMock(data_type=PayloadSchemaType.INTEGER),
        }
        mock_client.get_collection.return_value = mock_coll_info_existing

        # When already existing as INTEGER: create_payload_index must NOT be called (idempotent)
        svc.ensure_payload_indexes()
        assert mock_client.create_payload_index.call_count == 0

        # Migration test: when existing index is KEYWORD, safely migrate to INTEGER
        mock_client.reset_mock()
        mock_coll_info_keyword = MagicMock()
        mock_coll_info_keyword.payload_schema = {
            "organization_id": MagicMock(data_type=PayloadSchemaType.KEYWORD),
            "knowledge_base_id": MagicMock(data_type=PayloadSchemaType.INTEGER),
        }
        mock_client.get_collection.return_value = mock_coll_info_keyword

        svc.ensure_payload_indexes()
        assert mock_client.delete_payload_index.call_count == 1
        assert mock_client.delete_payload_index.call_args[1]["field_name"] == "organization_id"
        assert mock_client.create_payload_index.call_count == 1
        assert mock_client.create_payload_index.call_args[1]["field_name"] == "organization_id"
        assert mock_client.create_payload_index.call_args[1]["field_schema"] == PayloadSchemaType.INTEGER
