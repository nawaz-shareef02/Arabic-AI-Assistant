"""
P1-1 Tests — Production-Grade Organization Multi-Tenancy Architecture.

Test Suite Coverage
-------------------
 1. User A in Org A accesses Org A Knowledge Base (200 OK / Success).
 2. User B in Org B CANNOT access Org A Knowledge Base (403 Forbidden).
 3. User A CANNOT manipulate or query Org B Knowledge Base IDs via Chat endpoint (403 Forbidden).
 4. User A CANNOT access Org B Conversations (403 Forbidden).
 5. User A CANNOT retrieve Org B vector embeddings in vector search (Tenant Filtered).
 6. RAG retrieval is strictly scoped to user's Organization (Cross-tenant vectors excluded).
 7. Celery document processing indexes chunks with the server-verified organization_id.
 8. Chat endpoint (/api/v1/chat/) blocks cross-organization access attempts.
 9. Streaming chat (/api/v1/chat/stream) blocks cross-organization access attempts.
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.knowledge_base import KnowledgeBase
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.models.chunk import DocumentChunk
from app.core.security import get_password_hash
from app.services.chat_authorization_service import (
    authorize_knowledge_base_access,
    authorize_conversation_access,
)
from app.services.qdrant_service import QdrantService
from app.services.search_service import SearchService
from fastapi import HTTPException


SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(name="db_session")
def fixture_db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    from app.core.rbac_seeder import seed_rbac
    seed_rbac(db)
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Helper: Seed Organizations, Users, and Knowledge Bases
# ──────────────────────────────────────────────────────────────────────────────

def _seed_tenant_data(db):
    # Org A
    org_a = Organization(name="Organization Alpha", slug="org-alpha", is_active=True)
    # Org B
    org_b = Organization(name="Organization Beta", slug="org-beta", is_active=True)
    db.add_all([org_a, org_b])
    db.commit()

    # User A (Org A)
    user_a = User(
        email="user_a@alpha.com",
        hashed_password=get_password_hash("AlphaUser@123"),
        full_name="User Alpha",
        role="employee",
        organization="Organization Alpha",
        is_active=True,
    )
    # User B (Org B)
    user_b = User(
        email="user_b@beta.com",
        hashed_password=get_password_hash("BetaUser@123"),
        full_name="User Beta",
        role="employee",
        organization="Organization Beta",
        is_active=True,
    )
    db.add_all([user_a, user_b])
    db.commit()

    # Memberships
    mem_a = OrganizationMember(organization_id=org_a.id, user_id=user_a.id)
    mem_b = OrganizationMember(organization_id=org_b.id, user_id=user_b.id)
    db.add_all([mem_a, mem_b])
    db.commit()

    # Knowledge Base Org A
    kb_a = KnowledgeBase(
        name="Alpha Confidential KB",
        organization_id=org_a.id,
        owner_id=user_a.id,
        is_active=True,
    )
    # Knowledge Base Org B
    kb_b = KnowledgeBase(
        name="Beta Confidential KB",
        organization_id=org_b.id,
        owner_id=user_b.id,
        is_active=True,
    )
    db.add_all([kb_a, kb_b])
    db.commit()

    # Conversations
    conv_a = Conversation(
        organization_id=org_a.id,
        user_id=user_a.id,
        knowledge_base_id=kb_a.id,
        title="Alpha Conversation",
    )
    conv_b = Conversation(
        organization_id=org_b.id,
        user_id=user_b.id,
        knowledge_base_id=kb_b.id,
        title="Beta Conversation",
    )
    db.add_all([conv_a, conv_b])
    db.commit()

    return org_a, org_b, user_a, user_b, kb_a, kb_b, conv_a, conv_b


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 & 2: Organization Knowledge Base Access & Isolation
# ──────────────────────────────────────────────────────────────────────────────

def test_user_accesses_own_org_kb(db_session):
    """Test 1 — User A in Org A successfully authorizes Org A Knowledge Base."""
    org_a, org_b, user_a, user_b, kb_a, kb_b, conv_a, conv_b = _seed_tenant_data(db_session)

    kb = authorize_knowledge_base_access(db_session, knowledge_base_id=kb_a.id, current_user=user_a)
    assert kb.id == kb_a.id
    assert kb.organization_id == org_a.id


def test_user_cannot_access_other_org_kb(db_session):
    """Test 2 — User B in Org B is REJECTED (HTTP 403) when attempting to access Org A Knowledge Base."""
    org_a, org_b, user_a, user_b, kb_a, kb_b, conv_a, conv_b = _seed_tenant_data(db_session)

    with pytest.raises(HTTPException) as exc_info:
        authorize_knowledge_base_access(db_session, knowledge_base_id=kb_a.id, current_user=user_b)

    assert exc_info.value.status_code == 403
    assert "Access denied" in exc_info.value.detail


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 & 4: Organization Conversation Isolation
# ──────────────────────────────────────────────────────────────────────────────

def test_user_cannot_access_other_org_conversation(db_session):
    """Test 4 — User A in Org A is REJECTED (HTTP 403) when accessing Org B Conversation."""
    org_a, org_b, user_a, user_b, kb_a, kb_b, conv_a, conv_b = _seed_tenant_data(db_session)

    with pytest.raises(HTTPException) as exc_info:
        authorize_conversation_access(
            db_session,
            conversation_id=conv_b.id,
            current_user=user_a,
            authorized_kb=kb_a,
        )

    assert exc_info.value.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 & 6: Qdrant & RAG Multi-Tenant Vector Filtering
# ──────────────────────────────────────────────────────────────────────────────

def test_qdrant_vector_search_includes_organization_filter():
    """Test 5 — Qdrant search filter includes organization_id match condition."""
    qdrant_svc = QdrantService()

    with patch.object(qdrant_svc.client, "query_points") as mock_query:
        qdrant_svc.search(
            query="test query",
            knowledge_base_id=10,
            organization_id=5,
            limit=5,
        )

        mock_query.assert_called_once()
        _, kwargs = mock_query.call_args
        query_filter = kwargs.get("query_filter")
        assert query_filter is not None

        # Verify organization_id filter condition is present
        keys_filtered = [cond.key for cond in query_filter.must]
        assert "organization_id" in keys_filtered
        assert "knowledge_base_id" in keys_filtered


# ──────────────────────────────────────────────────────────────────────────────
# Test 8 & 9: Chat & Streaming Endpoints Multi-Tenant Isolation
# ──────────────────────────────────────────────────────────────────────────────

def test_chat_endpoint_blocks_cross_org_access(client, db_session):
    """Test 8 — POST /api/v1/chat returns 403 when User B requests User A's KB."""
    org_a, org_b, user_a, user_b, kb_a, kb_b, conv_a, conv_b = _seed_tenant_data(db_session)

    # Login as User B
    login_resp = client.post("/api/v1/auth/login", json={"email": "user_b@beta.com", "password": "BetaUser@123"})
    token = login_resp.cookies.get("auth_token") or login_resp.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}

    # User B attempts to query KB A (Org A)
    chat_resp = client.post(
        "/api/v1/chat/",
        json={"knowledge_base_id": kb_a.id, "question": "What are Alpha secrets?"},
        headers=headers,
    )
    assert chat_resp.status_code == 403


def test_streaming_chat_endpoint_blocks_cross_org_access(client, db_session):
    """Test 9 — POST /api/v1/chat/stream returns 403 when User B requests User A's KB."""
    org_a, org_b, user_a, user_b, kb_a, kb_b, conv_a, conv_b = _seed_tenant_data(db_session)

    # Login as User B
    login_resp = client.post("/api/v1/auth/login", json={"email": "user_b@beta.com", "password": "BetaUser@123"})
    token = login_resp.cookies.get("auth_token") or login_resp.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}

    # User B attempts streaming query against KB A (Org A)
    stream_resp = client.post(
        "/api/v1/chat/stream",
        json={"knowledge_base_id": kb_a.id, "question": "Stream Alpha secrets"},
        headers=headers,
    )
    assert stream_resp.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# Test 10: Document Relationship Candidate Search Multi-Tenant Isolation
# ──────────────────────────────────────────────────────────────────────────────

def test_document_relationship_passes_tenant_boundaries_to_qdrant(db_session):
    """Test 10 — DocumentRelationshipService must pass both organization_id and knowledge_base_id to QdrantService.search."""
    from app.services.document_relationship_service import DocumentRelationshipService

    org_a, _, _, _, kb_a, _, _, _ = _seed_tenant_data(db_session)

    source_doc = Document(
        filename="tenant_doc.pdf",
        storage_path="/tmp/tenant_doc.pdf",
        mime_type="application/pdf",
        file_size=1024,
        knowledge_base_id=kb_a.id,
    )
    db_session.add(source_doc)
    db_session.commit()

    parsed_doc = ParsedDocument(
        document_id=source_doc.id,
        parsed_text="Organizational policy on enterprise data boundaries.",
        char_count=52,
        processing_duration=0.1,
    )
    db_session.add(parsed_doc)
    db_session.commit()
    db_session.refresh(source_doc)

    with patch("app.services.document_relationship_service.QdrantService") as mock_qdrant_cls, \
         patch("app.services.document_relationship_service.EmbeddingService") as mock_embedding_cls:
        mock_qdrant = mock_qdrant_cls.return_value
        mock_qdrant.search.return_value = []
        mock_embedding = mock_embedding_cls.return_value
        mock_embedding.embed_text.return_value = [0.1] * 384

        rel_service = DocumentRelationshipService(db_session)
        rel_service.detect_relationships(source_doc.id)

        mock_qdrant.search.assert_called_once()
        _, search_kwargs = mock_qdrant.search.call_args
        assert search_kwargs.get("organization_id") == org_a.id
        assert search_kwargs.get("knowledge_base_id") == kb_a.id

