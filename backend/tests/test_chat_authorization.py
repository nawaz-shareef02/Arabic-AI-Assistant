"""
P0-1 Security Tests — Chat Endpoint Authorization.

Tests matrix
------------
 1. Anonymous → POST /chat/        → 401
 2. Anonymous → POST /chat/stream  → 401
 3. User A → own KB → 200 (stateless, RAG mocked)
 4. User A → User B's KB → 403
 5. User A → User B's conversation → 403
 6. User A → own conversation → authorized (RAG mocked)
 7. Invalid / nonexistent KB → 403 (no 500, no DB error exposed)
 8. Streaming endpoint → authorization enforced before generation
 9. RAG retrieval remains scoped to authorized KB (KB ID not blindly trusted)
10. Existing authenticated streaming chat still works (smoke, RAG mocked)
11. Conversation KB mismatch → 403

Design
------
- Uses SQLite in-memory for speed and isolation (same pattern as test_auth.py).
- KB and Conversation records are seeded directly via SQLAlchemy (not via the
  RBAC-guarded API) so no RBAC roles need to be seeded for test setup.
- Mocks RAGService so tests never require Qdrant, Ollama, or real embeddings.
- User registration/login still goes through the full HTTP auth flow to obtain
  real JWT tokens — this tests the actual authentication mechanism.
"""

import pytest
import uuid as py_uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.models.knowledge_base import KnowledgeBase
from app.models.conversation import Conversation, ConversationStatus
from app.models.user import User

# ──────────────────────────────────────────────────────────────────────────────
# Test database setup (in-memory SQLite)
# ──────────────────────────────────────────────────────────────────────────────

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
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _register_and_login(client, email: str, password: str = "Secure@12345", organization: str = None) -> str:
    """Register a user via HTTP and return their JWT access token."""
    org_name = organization or f"Org for {email}"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "organization": org_name,
        },
    )
    resp = client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": password},
    )
    client.cookies.clear()
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _get_user_id(db_session, email: str) -> int:
    """Resolve integer user.id directly from the test DB using their email."""
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None, f"User not found in test DB: {email}"
    return user.id


def _seed_kb(db_session, owner_id: int, name: str = "Test KB") -> KnowledgeBase:
    """Insert a KnowledgeBase directly in the test DB, bypassing RBAC guards."""
    from app.models.organization import OrganizationMember
    mem = db_session.query(OrganizationMember).filter(OrganizationMember.user_id == owner_id).first()
    org_id = mem.organization_id if mem else 1

    kb = KnowledgeBase(
        uuid=py_uuid.uuid4(),
        name=name,
        organization_id=org_id,
        owner_id=owner_id,
        created_by=owner_id,
        is_active=True,
    )
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)
    return kb


def _seed_conversation(
    db_session, user_id: int, kb_id: int, title: str = "Test Conv"
) -> Conversation:
    """Insert a Conversation directly in the test DB, bypassing RBAC guards."""
    kb = db_session.get(KnowledgeBase, kb_id)
    org_id = kb.organization_id if kb else 1

    conv = Conversation(
        uuid=py_uuid.uuid4(),
        organization_id=org_id,
        user_id=user_id,
        knowledge_base_id=kb_id,
        title=title,
        status=ConversationStatus.ACTIVE.value,
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


# Minimal mock RAG response so tests never touch Ollama / Qdrant.
_MOCK_RAG_RESPONSE = {"answer": "Mock answer", "sources": []}


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Anonymous → POST /chat/ → 401
# ──────────────────────────────────────────────────────────────────────────────

def test_anonymous_chat_returns_401(client):
    """Test 1 — Unauthenticated POST /chat/ must return 401."""
    resp = client.post(
        "/api/v1/chat/",
        json={"question": "Hello", "knowledge_base_id": 1},
    )
    assert resp.status_code == 401, (
        f"Expected 401 for anonymous request but got {resp.status_code}: {resp.text}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Anonymous → POST /chat/stream → 401
# ──────────────────────────────────────────────────────────────────────────────

def test_anonymous_stream_returns_401(client):
    """Test 2 — Unauthenticated POST /chat/stream must return 401."""
    resp = client.post(
        "/api/v1/chat/stream",
        json={"question": "Hello", "knowledge_base_id": 1},
    )
    assert resp.status_code == 401, (
        f"Expected 401 for anonymous streaming request but got {resp.status_code}: {resp.text}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: User A → own KB → 200 (RAG mocked)
# ──────────────────────────────────────────────────────────────────────────────

def test_authenticated_user_accesses_own_kb(client, db_session):
    """Test 3 — Authenticated user with valid KB gets through authorization."""
    token_a = _register_and_login(client, "user_a_own@test.com")
    user_a_id = _get_user_id(db_session, "user_a_own@test.com")
    kb_a = _seed_kb(db_session, user_a_id, "User A KB")

    with patch("app.api.v1.chat.RAGService.ask", return_value=_MOCK_RAG_RESPONSE):
        resp = client.post(
            "/api/v1/chat/",
            json={"question": "What is this?", "knowledge_base_id": kb_a.id},
            headers={"Authorization": f"Bearer {token_a}"},
        )

    assert resp.status_code == 200, (
        f"Expected 200 for own-KB access but got {resp.status_code}: {resp.text}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: User A → User B's KB → 403
# ──────────────────────────────────────────────────────────────────────────────

def test_user_a_cannot_access_user_b_kb(client, db_session):
    """Test 4 — Cross-user KB access must be denied with 403."""
    token_a = _register_and_login(client, "user_a_xkb@test.com")
    token_b = _register_and_login(client, "user_b_xkb@test.com")
    user_b_id = _get_user_id(db_session, "user_b_xkb@test.com")

    # User B owns this KB.
    kb_b = _seed_kb(db_session, user_b_id, "User B Private KB")

    # User A attempts to chat using User B's KB ID.
    resp = client.post(
        "/api/v1/chat/",
        json={"question": "Can I read this?", "knowledge_base_id": kb_b.id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for cross-user KB access but got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    # Must not expose internal details.
    assert "knowledge base" in body["detail"].lower()
    assert "sql" not in body["detail"].lower()
    assert "traceback" not in body.get("detail", "").lower()


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: User A → User B's conversation → 403
# ──────────────────────────────────────────────────────────────────────────────

def test_user_a_cannot_access_user_b_conversation(client, db_session):
    """Test 5 — Cross-user conversation access must be denied with 403."""
    token_a = _register_and_login(client, "user_a_xconv@test.com")
    token_b = _register_and_login(client, "user_b_xconv@test.com")
    user_a_id = _get_user_id(db_session, "user_a_xconv@test.com")
    user_b_id = _get_user_id(db_session, "user_b_xconv@test.com")

    kb_a = _seed_kb(db_session, user_a_id, "KB of A")
    kb_b = _seed_kb(db_session, user_b_id, "KB of B")

    # User B creates a conversation.
    conv_b = _seed_conversation(db_session, user_b_id, kb_b.id, "User B conv")

    # User A sends a chat with their own KB ID but User B's conversation ID.
    resp = client.post(
        "/api/v1/chat/",
        json={
            "question": "IDOR attempt",
            "knowledge_base_id": kb_a.id,
            "conversation_id": conv_b.id,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for cross-user conversation IDOR but got {resp.status_code}: {resp.text}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: User A → own conversation → authorized (RAG mocked)
# ──────────────────────────────────────────────────────────────────────────────

def test_user_a_accesses_own_conversation(client, db_session):
    """Test 6 — User may access their own conversation within their own KB."""
    token_a = _register_and_login(client, "user_a_own_conv@test.com")
    user_a_id = _get_user_id(db_session, "user_a_own_conv@test.com")
    kb_a = _seed_kb(db_session, user_a_id, "KB A Own")
    conv_a = _seed_conversation(db_session, user_a_id, kb_a.id, "Conv A")

    with patch("app.api.v1.chat.RAGService.ask_with_history", return_value=_MOCK_RAG_RESPONSE):
        resp = client.post(
            "/api/v1/chat/",
            json={
                "question": "Continue our chat",
                "knowledge_base_id": kb_a.id,
                "conversation_id": conv_a.id,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )

    assert resp.status_code == 200, (
        f"Expected 200 for own conversation access but got {resp.status_code}: {resp.text}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Invalid / nonexistent KB → 403 (no 500, no internal details)
# ──────────────────────────────────────────────────────────────────────────────

def test_nonexistent_kb_returns_403_not_500(client, db_session):
    """Test 7 — A KB ID that does not exist must return 403, not 500 or 404."""
    token_a = _register_and_login(client, "user_a_noexist@test.com")

    resp = client.post(
        "/api/v1/chat/",
        json={"question": "Will this work?", "knowledge_base_id": 999999},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for nonexistent KB but got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    detail = body.get("detail", "")
    assert "sql" not in detail.lower()
    assert "exception" not in detail.lower()
    assert "traceback" not in detail.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: Streaming → authorization enforced before generation
# ──────────────────────────────────────────────────────────────────────────────

def test_stream_authorization_enforced_before_generation(client, db_session):
    """
    Test 8 — Streaming endpoint must reject unauthorized request with 403
    before any RAG/LLM generation begins.
    a) Cross-user KB request → 403 and RAGService.stream_ask is never called.
    """
    token_a = _register_and_login(client, "user_a_stream@test.com")
    token_b = _register_and_login(client, "user_b_stream@test.com")
    user_b_id = _get_user_id(db_session, "user_b_stream@test.com")
    kb_b = _seed_kb(db_session, user_b_id, "B Streaming KB")

    with patch("app.api.v1.chat.RAGService.stream_ask") as mock_stream:
        resp = client.post(
            "/api/v1/chat/stream",
            json={"question": "Steal data", "knowledge_base_id": kb_b.id},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for cross-user streaming but got {resp.status_code}: {resp.text}"
        )
        # Authorization must block before reaching RAGService.
        mock_stream.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 9: RAG scoped to authorized KB (not blindly trusted from client)
# ──────────────────────────────────────────────────────────────────────────────

def test_rag_receives_only_authorized_kb_id(client, db_session):
    """
    Test 9 — The KB ID passed to RAGService.ask() must be the server-verified
    KB's own ID, not the raw client-supplied integer.
    """
    token_a = _register_and_login(client, "user_a_scope@test.com")
    user_a_id = _get_user_id(db_session, "user_a_scope@test.com")
    kb_a = _seed_kb(db_session, user_a_id, "User A Scoped KB")
    kb_a_id = kb_a.id

    captured_kb_id = {}

    def mock_ask(question, knowledge_base_id, **kwargs):
        captured_kb_id["value"] = knowledge_base_id
        return _MOCK_RAG_RESPONSE

    with patch("app.api.v1.chat.RAGService.ask", side_effect=mock_ask):
        resp = client.post(
            "/api/v1/chat/",
            json={"question": "Scoped question", "knowledge_base_id": kb_a_id},
            headers={"Authorization": f"Bearer {token_a}"},
        )

    assert resp.status_code == 200, resp.text
    assert captured_kb_id["value"] == kb_a_id, (
        f"RAG received KB ID {captured_kb_id['value']} but expected {kb_a_id}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 10: Authenticated streaming still works (smoke)
# ──────────────────────────────────────────────────────────────────────────────

def test_authenticated_streaming_chat_still_works(client, db_session):
    """
    Test 10 — An authenticated user accessing their own KB via the streaming
    endpoint must receive a 200 response (RAG is mocked).
    """
    token_a = _register_and_login(client, "user_a_smokestream@test.com")
    user_a_id = _get_user_id(db_session, "user_a_smokestream@test.com")
    kb_a = _seed_kb(db_session, user_a_id, "User A Stream KB")

    def mock_stream_ask(question, knowledge_base_id, **kwargs):
        yield "Mock "
        yield "streaming "
        yield "response."

    with patch("app.api.v1.chat.RAGService.stream_ask", side_effect=mock_stream_ask):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"question": "Stream this", "knowledge_base_id": kb_a.id},
            headers={"Authorization": f"Bearer {token_a}"},
        )

    assert resp.status_code == 200, (
        f"Expected 200 for authenticated streaming but got {resp.status_code}: {resp.text}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 11: Conversation references wrong KB → 403
# ──────────────────────────────────────────────────────────────────────────────

def test_conversation_kb_mismatch_returns_403(client, db_session):
    """
    Test 11 — User provides their own conversation, but the request KB does not
    match the conversation's KB.  Closes the cross-KB vector exfiltration vector.
    """
    token_a = _register_and_login(client, "user_a_mismatch@test.com")
    user_a_id = _get_user_id(db_session, "user_a_mismatch@test.com")

    kb_a1 = _seed_kb(db_session, user_a_id, "KB A1")
    kb_a2 = _seed_kb(db_session, user_a_id, "KB A2")

    # Create a conversation in KB A1.
    conv = _seed_conversation(db_session, user_a_id, kb_a1.id, "Conv in KB A1")

    # Send a chat request pointing to KB A2, but using KB A1's conversation.
    resp = client.post(
        "/api/v1/chat/",
        json={
            "question": "Cross KB IDOR?",
            "knowledge_base_id": kb_a2.id,
            "conversation_id": conv.id,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for KB-conversation mismatch but got {resp.status_code}: {resp.text}"
    )
    assert "knowledge base" in resp.json()["detail"].lower()
