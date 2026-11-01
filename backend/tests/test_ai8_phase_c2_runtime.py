"""
test_ai8_phase_c2_runtime.py — AI-8 Phase C.2 Authoritative Runtime Accounting Reconciliation Test Suite.

Verifies:
1. same Idempotency-Key -> one ledger event
2. same retry -> same ledger event
3. different requests -> different ledger events
4. request ID does not act as quota idempotency authority
5. stateless retry does not rely on uuid4() for deduplication
6. conversation retry behavior
7. ledger-write failure behavior (non-streaming raises RuntimeError; streaming logs CRITICAL alert)
8. missing organization behavior (raises ValueError invariant violation)
9. exact stream usage (status=EXACT, authoritative tokens)
10. unavailable stream usage (status=UNAVAILABLE, tokens=NULL, UNKNOWN != 0)
11. internal AI calls remain non-quota-bearing
12. existing message persistence behavior remains compatible
13. DB connections released before LLM inference
"""

import logging
import uuid as py_uuid
from unittest.mock import MagicMock, patch
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.organization import Organization
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.ai_usage_event import (
    AIUsageEvent,
    AIUsageEventType,
    AIUsageStatus,
    QUOTA_BEARING_EVENT_TYPES,
)
from app.repositories.ai_usage_repository import AIUsageRepository
from app.services.llm.base import GenerationResult, StreamingResult, TokenUsage
from app.services.rag_service import RAGService


@pytest.fixture
def db_engine():
    """Isolated in-memory SQLite database engine with foreign keys enabled."""
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_session_factory(db_engine):
    """Provides a thread-safe sessionmaker bound to the test engine with expire_on_commit=False."""
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def db_session(test_session_factory):
    """Provides a fresh DB session connected to the test engine."""
    session = test_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def patch_session_local(test_session_factory):
    """Patches SessionLocal so isolated session calls in RAGService connect to the test engine."""
    with patch("app.database.session.SessionLocal", test_session_factory):
        yield test_session_factory


@pytest.fixture
def seed_data(test_session_factory):
    """Seeds test Org, User, KB, Conversation, detaching them safely with scalar IDs captured."""
    session = test_session_factory()
    try:
        org = Organization(name="Acme Corp", slug=f"acme-{py_uuid.uuid4().hex[:6]}", is_active=True)
        session.add(org)
        session.commit()
        session.refresh(org)

        user = User(
            email=f"user-{py_uuid.uuid4().hex[:6]}@acme.com",
            hashed_password="hash",
            full_name="Alice Doe",
            is_active=True,
            organization=org.name,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        kb = KnowledgeBase(name="KB 1", organization_id=org.id, owner_id=user.id, is_active=True)
        session.add(kb)
        session.commit()
        session.refresh(kb)

        conv = Conversation(organization_id=org.id, knowledge_base_id=kb.id, user_id=user.id)
        session.add(conv)
        session.commit()
        session.refresh(conv)

        return {
            "org_id": org.id,
            "user_id": user.id,
            "kb_id": kb.id,
            "conv_id": conv.id,
            "user": user,
        }
    finally:
        session.close()


def _make_rag_service(db_session):
    """Constructs RAGService with external retrieval & LLM dependencies mocked."""
    with patch("app.services.rag_service.SearchService"), \
         patch("app.services.rag_service.LLMFactory"), \
         patch("app.services.rag_service.QueryExpansionService"), \
         patch("app.services.rag_service.get_reranker"):
        rag = RAGService(db_session)
        rag.search_service = MagicMock()
        rag.search_service.hybrid_search.return_value = [
            MagicMock(text="Context about Saudi Vision 2030", score=0.95, chunk_uuid="c1", parsed_document_id=10)
        ]
        rag._reranker = MagicMock()
        rag._reranker.rerank.return_value = [
            MagicMock(text="Context about Saudi Vision 2030", score=0.95, chunk_uuid="c1", parsed_document_id=10)
        ]
        return rag


# ===========================================================================
# 1. same Idempotency-Key -> one ledger event
# ===========================================================================

def test_same_idempotency_key_produces_one_ledger_event(
    test_session_factory, patch_session_local, seed_data
):
    """Two identical requests sharing the same Idempotency-Key create only 1 ledger event."""
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=40, completion_tokens=60, total_tokens=100, is_terminal=True, is_exact=True)

    with patch("app.services.rag_service.PromptSecurityService"):
        # Execution 1
        rag1 = _make_rag_service(test_session_factory())
        rag1.llm.generate.return_value = GenerationResult("Answer 1", token_usage=usage, model="qwen3:8b")
        resp1 = rag1.ask(
            question="What is Vision 2030?",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            idempotency_key="idemp-key-shared-1",
        )

        # Execution 2 (duplicate client invocation with same idempotency key)
        rag2 = _make_rag_service(test_session_factory())
        rag2.llm.generate.return_value = GenerationResult("Answer 1", token_usage=usage, model="qwen3:8b")
        resp2 = rag2.ask(
            question="What is Vision 2030?",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            idempotency_key="idemp-key-shared-1",
        )

    assert resp1["answer"] == "Answer 1"
    assert resp2["answer"] == "Answer 1"

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_ASK")
        assert total == 1
        assert events[0].idempotency_key == "client:idemp-key-shared-1"
        assert events[0].total_tokens == 100
    finally:
        query_session.close()


# ===========================================================================
# 2. same retry -> same ledger event
# ===========================================================================

def test_same_retry_returns_same_ledger_event(
    test_session_factory, patch_session_local, seed_data
):
    """A retry invocation with the same idempotency key returns the existing event."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=30, completion_tokens=70, total_tokens=100, is_terminal=True, is_exact=True)

    ev1 = rag._record_usage_event(
        event_type=AIUsageEventType.RAG_ASK,
        token_usage=usage,
        organization_id=org_id,
        user_id=user_id,
        idempotency_key="retry-token-999",
    )
    assert ev1 is not None

    ev2 = rag._record_usage_event(
        event_type=AIUsageEventType.RAG_ASK,
        token_usage=usage,
        organization_id=org_id,
        user_id=user_id,
        idempotency_key="retry-token-999",
    )
    assert ev2 is not None
    assert ev1.id == ev2.id
    assert ev1.uuid == ev2.uuid


# ===========================================================================
# 3. different requests -> different ledger events
# ===========================================================================

def test_different_requests_produce_different_ledger_events(
    test_session_factory, patch_session_local, seed_data
):
    """Two legitimate different requests produce distinct ledger rows with unique identities."""
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage1 = TokenUsage(prompt_tokens=20, completion_tokens=30, total_tokens=50, is_terminal=True, is_exact=True)
    usage2 = TokenUsage(prompt_tokens=25, completion_tokens=35, total_tokens=60, is_terminal=True, is_exact=True)

    with patch("app.services.rag_service.PromptSecurityService"):
        rag1 = _make_rag_service(test_session_factory())
        rag1.llm.generate.return_value = GenerationResult("Ans 1", token_usage=usage1, model="qwen3:8b")
        rag1.ask(
            question="Question 1?",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            idempotency_key="req-client-A",
        )

        rag2 = _make_rag_service(test_session_factory())
        rag2.llm.generate.return_value = GenerationResult("Ans 2", token_usage=usage2, model="qwen3:8b")
        rag2.ask(
            question="Question 2?",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            idempotency_key="req-client-B",
        )

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_ASK")
        assert total == 2
        keys = {e.idempotency_key for e in events}
        assert keys == {"client:req-client-A", "client:req-client-B"}
    finally:
        query_session.close()


# ===========================================================================
# 4. request ID does not act as quota idempotency authority
# ===========================================================================

def test_request_id_does_not_act_as_quota_idempotency_authority(
    test_session_factory, patch_session_local, seed_data
):
    """Varying request_id does NOT cause duplicate billing; client idempotency_key is authoritative."""
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=15, completion_tokens=25, total_tokens=40, is_terminal=True, is_exact=True)

    with patch("app.services.rag_service.PromptSecurityService"):
        # First request with req_id = 'req-attempt-1'
        rag1 = _make_rag_service(test_session_factory())
        rag1.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="qwen3:8b")
        rag1.ask(
            question="Question with varying req_id",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            request_id="req-proxy-attempt-1",
            idempotency_key="stable-user-intent-101",
        )

        # Retry through proxy generating new request_id = 'req-attempt-2'
        rag2 = _make_rag_service(test_session_factory())
        rag2.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="qwen3:8b")
        rag2.ask(
            question="Question with varying req_id",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            request_id="req-proxy-attempt-2",
            idempotency_key="stable-user-intent-101",
        )

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_ASK")
        # Authoritative idempotency deduplicated them despite different request_ids!
        assert total == 1
        assert events[0].idempotency_key == "client:stable-user-intent-101"
        assert events[0].request_id == "req-proxy-attempt-1"
    finally:
        query_session.close()


# ===========================================================================
# 5. stateless retry does not rely on uuid4() for deduplication
# ===========================================================================

def test_stateless_retry_does_not_rely_on_uuid4_for_deduplication(
    test_session_factory, patch_session_local, seed_data
):
    """Stateless retry deduplication relies on client idempotency key; unkeyed requests get distinct keys."""
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30, is_terminal=True, is_exact=True)

    with patch("app.services.rag_service.PromptSecurityService"):
        # A: Client retries stateless request using stable idempotency key
        rag_retry1 = _make_rag_service(test_session_factory())
        rag_retry1.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="q")
        rag_retry1.ask(
            question="Stateless retry query",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            idempotency_key="stateless-client-idem-key",
        )

        rag_retry2 = _make_rag_service(test_session_factory())
        rag_retry2.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="q")
        rag_retry2.ask(
            question="Stateless retry query",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
            idempotency_key="stateless-client-idem-key",
        )

        # B: Two separate unkeyed requests without client key produce 2 distinct random events
        rag_unkeyed1 = _make_rag_service(test_session_factory())
        rag_unkeyed1.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="q")
        rag_unkeyed1.ask(
            question="Unkeyed query",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
        )

        rag_unkeyed2 = _make_rag_service(test_session_factory())
        rag_unkeyed2.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="q")
        rag_unkeyed2.ask(
            question="Unkeyed query",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
        )

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_ASK")
        # 1 from keyed retry + 2 from separate unkeyed calls = 3 total
        assert total == 3
        keyed_events = [e for e in events if e.idempotency_key == "client:stateless-client-idem-key"]
        assert len(keyed_events) == 1
    finally:
        query_session.close()


# ===========================================================================
# 6. conversation retry behavior
# ===========================================================================

def test_conversation_retry_behavior(
    test_session_factory, patch_session_local, seed_data
):
    """Conversational fallback anchors to message turn identity when client key is omitted."""
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    conv_id = seed_data["conv_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=50, completion_tokens=50, total_tokens=100, is_terminal=True, is_exact=True)

    with patch("app.services.rag_service.PromptSecurityService"):
        session1 = test_session_factory()
        rag1 = _make_rag_service(session1)
        rag1.llm.generate.return_value = GenerationResult("Conv Ans", token_usage=usage, model="q")

        # Conversational ask turn 1
        rag1.ask_with_history(
            question="Conv question 1",
            knowledge_base_id=kb_id,
            conversation_id=conv_id,
            user_id=user_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
        )

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_CONV_ASK")
        assert total == 1
        key = events[0].idempotency_key
        assert key.startswith(f"rag:RAG_CONV_ASK:conv:{conv_id}:msg:")
    finally:
        query_session.close()


# ===========================================================================
# 7. ledger-write failure behavior
# ===========================================================================

def test_ledger_write_failure_behavior_non_streaming(
    test_session_factory, patch_session_local, seed_data
):
    """In non-streaming, permanent ledger failure raises RuntimeError, failing request."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, is_terminal=True, is_exact=True)
    rag.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="q")

    # Mock AIUsageRepository.create_event to always fail (e.g. database down)
    with patch("app.services.rag_service.PromptSecurityService"), \
         patch.object(AIUsageRepository, "create_event", side_effect=Exception("Database connection dead")):

        with pytest.raises(RuntimeError, match="Authoritative AI usage ledger write failed"):
            rag.ask(
                question="What is 2030?",
                knowledge_base_id=kb_id,
                organization_id=org_id,
                user=MagicMock(id=user_id),
            )


def test_ledger_write_failure_behavior_streaming(
    test_session_factory, patch_session_local, seed_data, caplog
):
    """In streaming, ledger failure logs CRITICAL alert for C.3 durable spool handoff without crashing client."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, is_terminal=True, is_exact=True)
    streaming_res = StreamingResult(
        generator=iter(["Stream ", "chunk"]),
        model="qwen3:8b",
        usage_box=[usage],
    )
    rag.llm.stream_generate.return_value = streaming_res

    with patch("app.services.rag_service.PromptSecurityService"), \
         patch.object(AIUsageRepository, "create_event", side_effect=Exception("DB pool exhausted")), \
         caplog.at_level(logging.CRITICAL):

        tokens = list(
            rag.stream_ask(
                question="Stream with failing write?",
                knowledge_base_id=kb_id,
                organization_id=org_id,
                user=MagicMock(id=user_id),
            )
        )

    # Client still gets the stream chunks
    assert tokens == ["Stream ", "chunk"]
    # Critical alert logged for Phase C.3 spool handoff
    assert any("AI_ACCOUNTING_WRITE_FAILURE" in record.message for record in caplog.records)
    assert any("HANDOFF_TO_C3_SPOOL" in record.message for record in caplog.records)


# ===========================================================================
# 8. missing organization behavior
# ===========================================================================

def test_missing_organization_raises_invariant_violation(
    test_session_factory, patch_session_local, seed_data
):
    """Omitting organization_id on a quota-bearing path raises ValueError invariant violation."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30, is_exact=True)
    rag.llm.generate.return_value = GenerationResult("Ans", token_usage=usage, model="q")

    with patch("app.services.rag_service.PromptSecurityService"):
        # Organization missing and unresolvable from database
        with pytest.raises(ValueError, match="Authoritative tenant invariant violation: organization_id is required"):
            rag.ask(
                question="No org question?",
                knowledge_base_id=99999,  # Unresolvable KB
                organization_id=None,
                user=MagicMock(id=user_id),
            )


# ===========================================================================
# 9. exact stream usage
# ===========================================================================

def test_exact_stream_usage_emits_authoritative_ledger_event(
    test_session_factory, patch_session_local, seed_data
):
    """Streaming with exact terminal tokens emits EXACT status with authoritative counts."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(
        prompt_tokens=35,
        completion_tokens=65,
        total_tokens=100,
        is_terminal=True,
        is_exact=True,
    )
    streaming_res = StreamingResult(
        generator=iter(["Exact ", "stream ", "data."]),
        model="qwen3:8b",
        usage_box=[usage],
    )
    rag.llm.stream_generate.return_value = streaming_res

    with patch("app.services.rag_service.PromptSecurityService"):
        tokens = list(
            rag.stream_ask(
                question="Exact stream test?",
                knowledge_base_id=kb_id,
                organization_id=org_id,
                user=MagicMock(id=user_id),
                idempotency_key="stream-exact-key-1",
            )
        )

    assert tokens == ["Exact ", "stream ", "data."]

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_STREAM")
        assert total == 1
        event = events[0]
        assert event.event_type == AIUsageEventType.RAG_STREAM.value
        assert event.status == AIUsageStatus.EXACT.value
        assert event.is_exact is True
        assert event.is_quota_bearing is True
        assert event.prompt_tokens == 35
        assert event.completion_tokens == 65
        assert event.total_tokens == 100
        assert event.idempotency_key == "client:stream-exact-key-1"
    finally:
        query_session.close()


# ===========================================================================
# 10. unavailable stream usage
# ===========================================================================

def test_unavailable_stream_usage_stores_null_tokens(
    test_session_factory, patch_session_local, seed_data
):
    """When stream metadata is missing, status=UNAVAILABLE and tokens=NULL (UNKNOWN != 0)."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    # Stream completes but terminal chunk did NOT provide token_usage
    streaming_res = StreamingResult(
        generator=iter(["Part1 ", "Part2"]),
        model="qwen3:8b",
        usage_box=[None],  # UNAVAILABLE
    )
    rag.llm.stream_generate.return_value = streaming_res

    with patch("app.services.rag_service.PromptSecurityService"):
        tokens = list(
            rag.stream_ask(
                question="Inexact stream?",
                knowledge_base_id=kb_id,
                organization_id=org_id,
                user=MagicMock(id=user_id),
                idempotency_key="unavail-stream-key",
            )
        )

    assert tokens == ["Part1 ", "Part2"]

    query_session = test_session_factory()
    try:
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_STREAM")
        assert total == 1
        event = events[0]
        assert event.status == AIUsageStatus.UNAVAILABLE.value
        assert event.is_exact is False
        # CRITICAL: Tokens must be None, NEVER fabricated or coerced to 0!
        assert event.prompt_tokens is None
        assert event.completion_tokens is None
        assert event.total_tokens is None
    finally:
        query_session.close()


# ===========================================================================
# 11. internal AI calls remain non-quota-bearing
# ===========================================================================

def test_internal_ai_calls_remain_non_quota_bearing(test_session_factory, seed_data):
    """QueryRewriter, QueryExpansion, TitleService, Warmup must remain non-quota-bearing."""
    for internal_type in [
        AIUsageEventType.QUERY_REWRITE,
        AIUsageEventType.QUERY_EXPANSION,
        AIUsageEventType.TITLE_GENERATION,
        AIUsageEventType.EVALUATION,
        AIUsageEventType.WARMUP,
    ]:
        assert internal_type not in QUOTA_BEARING_EVENT_TYPES
        assert internal_type.value not in QUOTA_BEARING_EVENT_TYPES

    session = test_session_factory()
    try:
        repo = AIUsageRepository(session)
        with pytest.raises(ValueError, match="cannot be marked quota-bearing"):
            repo.create_event(
                event_type=AIUsageEventType.QUERY_REWRITE,
                idempotency_key="bad-quota-internal",
                organization_id=seed_data["org_id"],
                is_quota_bearing=True,  # VIOLATION: must be rejected
                prompt_tokens=10,
                completion_tokens=20,
            )
    finally:
        session.close()


# ===========================================================================
# 12. existing message persistence behavior remains compatible
# ===========================================================================

def test_existing_message_persistence_behavior_remains_compatible(
    test_session_factory, patch_session_local, seed_data
):
    """Conversational assistant message is saved with role ASSISTANT and tokens preserved."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    conv_id = seed_data["conv_id"]
    user_id = seed_data["user_id"]

    usage = TokenUsage(
        prompt_tokens=25,
        completion_tokens=75,
        total_tokens=100,
        is_terminal=True,
        is_exact=True,
    )
    rag.llm.generate.return_value = GenerationResult("Grounded answer.", token_usage=usage, model="q")

    with patch("app.services.rag_service.PromptSecurityService"):
        resp = rag.ask_with_history(
            question="Question 1",
            knowledge_base_id=kb_id,
            conversation_id=conv_id,
            user_id=user_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
        )

    assert resp["answer"] == "Grounded answer."

    query_session = test_session_factory()
    try:
        assistant_msg = (
            query_session.query(Message)
            .filter(Message.conversation_id == conv_id, Message.role == MessageRole.ASSISTANT)
            .first()
        )
        assert assistant_msg is not None
        assert assistant_msg.content == "Grounded answer."
        assert assistant_msg.prompt_tokens == 25
        assert assistant_msg.completion_tokens == 75
        assert assistant_msg.total_tokens == 100

        # And exactly 1 ledger event was created
        repo = AIUsageRepository(query_session)
        events, total = repo.list_events(organization_id=org_id, event_type="RAG_CONV_ASK")
        assert total == 1
    finally:
        query_session.close()


# ===========================================================================
# 13. DB connections are still released before LLM inference
# ===========================================================================

def test_db_connections_released_before_llm_inference(
    test_session_factory, patch_session_local, seed_data
):
    """Guarantees _release_db() is called BEFORE LLM generation/streaming begins."""
    session = test_session_factory()
    rag = _make_rag_service(session)
    org_id = seed_data["org_id"]
    kb_id = seed_data["kb_id"]
    user_id = seed_data["user_id"]

    db_released_before_generate = False

    def spy_release_db():
        nonlocal db_released_before_generate
        db_released_before_generate = True

    rag._release_db = spy_release_db

    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30, is_exact=True)

    def spy_generate(prompt, *args, **kwargs):
        assert db_released_before_generate is True, "DB was not released prior to LLM generate!"
        return GenerationResult("Answer", token_usage=usage, model="q")

    rag.llm.generate.side_effect = spy_generate

    with patch("app.services.rag_service.PromptSecurityService"):
        rag.ask(
            question="Test release db",
            knowledge_base_id=kb_id,
            organization_id=org_id,
            user=MagicMock(id=user_id),
        )

    assert db_released_before_generate is True
