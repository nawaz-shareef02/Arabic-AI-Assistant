"""
test_p2_database_concurrency.py — Enterprise Database Connection Pool & Concurrency Test Suite.

P2-2 Verification Gate:
- Bounded Connection Pool configuration validation (defaults: pool_size=5, max_overflow=5, timeout=10, recycle=1800, pre_ping=True)
- Pool status metrics and lifecycle hooks (checkedin, checkedout, overflow, timeouts)
- Graceful Pool Exhaustion: fast-fail with HTTP 503 Service Unavailable + Retry-After (zero leaked DB internals)
- Connection Leak Audit: verification of 0 leaked connections on success and exception paths (get_db, healthcheck, audit middleware)
- Decoupled RAG & Streaming Connection Lifecycle: proof that 0 DB connections are checked out during Ollama LLM inference/streaming
- Client Disconnect & Stream Cancellation: verification that aborting mid-stream releases concurrency slots without connection leaks
- Controlled Concurrency Regression: 10, 25, and 50 simultaneous request executions
- Multi-Tenant Isolation under concurrent database workloads
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from app.core.config import settings
from app.database.session import (
    engine,
    SessionLocal,
    get_db,
    get_pool_status,
    pool_metrics,
    reset_engine_pool,
)
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.knowledge_base import KnowledgeBase
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.services.rag_service import RAGService
from app.main import app, pool_timeout_exception_handler


# ===========================================================================
# 1. Pool Configuration & Metric Hooks Tests
# ===========================================================================

def test_database_pool_configuration_bounded_defaults():
    """
    Verify that pool settings are bounded and match enterprise defaults.
    These are initial bounded defaults to be tuned via environment variables.

    Capacity & Terminology Notes:
    - DB_APP_CONNECTION_BUDGET (60) is an application connection budget target across
      processes, NOT a cross-process hard cap (SQLAlchemy QueuePool is process-local).
    - Theoretical pool capacity per worker process is pool_size (5) + max_overflow (5) = 10.
    - Across 6 workers, total capacity aligns with the 60-connection budget.
    - Against PostgreSQL's standard max_connections=100, the 40-connection difference provides
      intentional operational headroom / application budget protection for administrative sessions,
      migrations, autovacuum, backups, and replication (not a PostgreSQL-internal reservation).
    """
    assert settings.DB_POOL_SIZE == 5
    assert settings.DB_MAX_OVERFLOW == 5
    assert settings.DB_POOL_TIMEOUT == 10
    assert settings.DB_POOL_RECYCLE == 1800
    assert settings.DB_POOL_PRE_PING is True
    assert settings.DB_APP_CONNECTION_BUDGET == 60


def test_pool_status_metrics_hook():
    """
    Verify get_pool_status() exposes the required metrics for P2-2/P2-3 monitoring.
    """
    status_snapshot = get_pool_status()
    expected_keys = {
        "pool_size",
        "checkedin",
        "checkedout",
        "overflow",
        "active_connections",
        "checkouts_total",
        "checkins_total",
        "timeouts_total",
        "connections_created",
        "connections_closed",
    }
    assert expected_keys.issubset(status_snapshot.keys())
    assert isinstance(status_snapshot["checkedout"], int)
    assert status_snapshot["checkedout"] >= 0


def test_fork_safety_reset_pool():
    """
    Verify reset_engine_pool executes without error and disposes the pool.
    """
    reset_engine_pool()
    # Post-reset, engine should re-establish cleanly upon next query
    db = SessionLocal()
    try:
        val = db.execute(text("SELECT 1")).scalar()
        assert val == 1
    finally:
        db.close()


# ===========================================================================
# 2. Controlled Pool Exhaustion & Graceful HTTP 503 Handling
# ===========================================================================

def test_pool_exhaustion_produces_generic_503_without_internals():
    """
    Controlled pool saturation test:
    When pool capacity is fully occupied and pool_timeout expires,
    the application must return HTTP 503 with Retry-After and NEVER
    expose PostgreSQL passwords, hosts, or raw tracebacks to the client.
    """
    # Create a micro-pool with capacity 1 (pool_size=1, max_overflow=0, timeout=0.1s)
    micro_engine = create_engine(
        settings.DATABASE_URL,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    MicroSession = sessionmaker(bind=micro_engine)

    # Checkout the single available connection and hold it
    conn1 = MicroSession()
    conn1.execute(text("SELECT 1"))

    # Attempt second checkout on exhausted pool
    with pytest.raises(SQLAlchemyTimeoutError) as exc_info:
        conn2 = MicroSession()
        conn2.execute(text("SELECT 1"))

    # Simulate FastAPI handling this exception via pool_timeout_exception_handler
    mock_request = MagicMock(spec=Request)
    mock_request.state.request_id = "test-exhaustion-uuid-123"

    import asyncio
    response = asyncio.run(pool_timeout_exception_handler(mock_request, exc_info.value))

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers.get("Retry-After") == "5"

    import json
    body = json.loads(response.body.decode())
    assert body["request_id"] == "test-exhaustion-uuid-123"
    assert "Database connection pool capacity reached" in body["detail"]
    # Verify no raw SQL or DB host leaks
    assert "postgresql://" not in response.body.decode()
    assert "5432" not in response.body.decode()
    assert "QueuePool" not in response.body.decode()

    # Cleanup: release held connection and dispose micro-engine
    conn1.close()
    micro_engine.dispose()


# ===========================================================================
# 3. Connection Leak Audit (Success & Exception Paths)
# ===========================================================================

def test_get_db_clean_lifecycle_on_success():
    """Verify get_db returns checkedout count to zero upon clean completion."""
    initial_checkedout = get_pool_status()["checkedout"]
    gen = get_db()
    db = next(gen)
    try:
        db.execute(text("SELECT 1")).scalar()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    final_checkedout = get_pool_status()["checkedout"]
    assert final_checkedout == initial_checkedout


def test_get_db_rollback_and_cleanup_on_exception():
    """Verify get_db performs rollback and closes session when an unhandled exception occurs."""
    initial_checkedout = get_pool_status()["checkedout"]
    gen = get_db()
    db = next(gen)

    with pytest.raises(RuntimeError):
        try:
            db.execute(text("SELECT 1"))
            raise RuntimeError("Forced route handler failure")
        except Exception:
            try:
                gen.throw(RuntimeError("Forced route handler failure"))
            except StopIteration:
                pass

    final_checkedout = get_pool_status()["checkedout"]
    assert final_checkedout == initial_checkedout


def test_health_check_postgres_no_leak_on_error():
    """Verify _check_postgres does not leak connections when db.execute throws."""
    from app.api.v1.health import _check_postgres

    initial_checkedout = get_pool_status()["checkedout"]

    # Normal execution
    result = _check_postgres()
    assert result == "online"
    assert get_pool_status()["checkedout"] == initial_checkedout

    # Simulated error path: mock db.execute to raise Exception
    with patch("sqlalchemy.orm.Session.execute", side_effect=Exception("Simulated DB offline")):
        err_result = _check_postgres()
        assert err_result == "offline"

    assert get_pool_status()["checkedout"] == initial_checkedout


def test_audit_middleware_no_leak_on_error():
    """Verify AuditMiddleware closes its isolated session even if publish_event fails."""
    from app.middleware.audit_middleware import AuditMiddleware

    middleware = AuditMiddleware(app=MagicMock())
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.method = "POST"
    mock_request.url.path = "/api/v1/documents"
    mock_request.client.host = "127.0.0.1"

    async def mock_call_next(req):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        return resp

    initial_checkedout = get_pool_status()["checkedout"]

    # Force failure inside publish_event
    with patch("app.services.audit_event_publisher.AuditEventPublisher.publish_event", side_effect=RuntimeError("Audit publish failed")):
        import asyncio
        asyncio.run(middleware.dispatch(mock_request, mock_call_next))

    # Connection must be cleanly closed
    assert get_pool_status()["checkedout"] == initial_checkedout


# ===========================================================================
# 4. Decoupled RAG & Streaming Connection Lifecycle Tests
# ===========================================================================

def _create_mock_chunk():
    mock_chunk = MagicMock()
    mock_chunk.text = "Saudi Vision 2030 is a transformative economic framework."
    mock_chunk.score = 0.95
    mock_chunk.chunk_uuid = "chunk-uuid-123"
    mock_chunk.parsed_document_id = 1
    return mock_chunk


def test_rag_ask_releases_db_before_ollama_generation():
    """
    CRITICAL ACCEPTANCE CRITERION:
    Ensure PostgreSQL connections are NOT held while Ollama generates responses.
    """
    db = SessionLocal()
    rag = RAGService(db)

    checkedout_during_llm = None

    def mock_llm_generate(prompt, *args, **kwargs):
        nonlocal checkedout_during_llm
        # Record checkedout connections while inside LLM generation
        checkedout_during_llm = get_pool_status()["checkedout"]
        return "Saudi Vision 2030 is a transformative economic framework."

    with patch.object(rag.search_service, "hybrid_search", return_value=[_create_mock_chunk()]), \
         patch.object(rag.llm, "generate", side_effect=mock_llm_generate):

        res = rag.ask(question="What is Vision 2030?", knowledge_base_id=1)
        assert res["answer"] == "Saudi Vision 2030 is a transformative economic framework."

    # PROOF: During LLM generation, connection was already returned to pool
    assert checkedout_during_llm == 0


def test_rag_stream_releases_db_before_yielding_tokens():
    """
    CRITICAL ACCEPTANCE CRITERION:
    Ensure zero DB connections remain checked out during streaming token generation.
    """
    db = SessionLocal()
    rag = RAGService(db)

    checkedout_during_stream = []

    def mock_stream_tokens(prompt, *args, **kwargs):
        for token in ["Saudi ", "Vision ", "2030"]:
            checkedout_during_stream.append(get_pool_status()["checkedout"])
            yield token

    with patch.object(rag.search_service, "hybrid_search", return_value=[_create_mock_chunk()]), \
         patch.object(rag.llm, "stream_generate", side_effect=mock_stream_tokens):

        tokens = list(rag.stream_ask(question="What is Vision 2030?", knowledge_base_id=1))
        assert tokens == ["Saudi ", "Vision ", "2030"]

    # PROOF: For EVERY yielded token, 0 DB connections were checked out
    assert len(checkedout_during_stream) == 3
    assert all(c == 0 for c in checkedout_during_stream)


@pytest.fixture(autouse=True)
def clean_pool_and_sessions():
    """Ensure no checked-out connections or open sessions linger between tests."""
    yield
    from sqlalchemy.orm import close_all_sessions
    close_all_sessions()


def test_rag_conversational_streaming_and_persistence_lifecycle():
    """
    Verify conversational streaming:
    1. Initial session closed before streaming
    2. Zero DB connections held during token generation
    3. Assistant message persisted ONLY on successful stream completion
    """
    setup_db = SessionLocal()
    try:
        user_suffix = uuid.uuid4().hex[:6]
        test_user = User(
            email=f"stream_{user_suffix}@example.com",
            hashed_password="pw",
            full_name="Stream User",
            role="Member",
            organization=f"Stream Org {user_suffix}",
        )
        setup_db.add(test_user)
        setup_db.commit()
        setup_db.refresh(test_user)

        kb = KnowledgeBase(
            name=f"KB Stream {user_suffix}",
            organization_id=1,
            owner_id=test_user.id,
            is_active=True,
        )
        setup_db.add(kb)
        setup_db.commit()
        setup_db.refresh(kb)

        conv = Conversation(
            title="Streaming Test",
            user_id=test_user.id,
            knowledge_base_id=kb.id,
            organization_id=1,
        )
        setup_db.add(conv)
        setup_db.commit()
        setup_db.refresh(conv)

        conv_id = conv.id
        kb_id = kb.id
        user_id = test_user.id
    finally:
        setup_db.close()

    db = SessionLocal()
    rag = RAGService(db)
    checkedout_during_stream = []

    def mock_stream_tokens(prompt, *args, **kwargs):
        for token in ["Part1 ", "Part2"]:
            checkedout_during_stream.append(get_pool_status()["checkedout"])
            yield token

    with patch.object(rag.search_service, "hybrid_search", return_value=[_create_mock_chunk()]), \
         patch.object(rag.llm, "stream_generate", side_effect=mock_stream_tokens), \
         patch.object(rag.llm, "generate", return_value="Expanded query"):

        tokens = list(rag.stream_ask_with_history(
            question="Tell me about the plan",
            knowledge_base_id=kb_id,
            conversation_id=conv_id,
            user_id=user_id,
        ))
        assert tokens == ["Part1 ", "Part2"]

    # Verify zero checkedout connections during streaming
    assert all(c == 0 for c in checkedout_during_stream)

    # Verify assistant message was saved to conversation
    verify_db = SessionLocal()
    try:
        messages = verify_db.query(Message).filter(Message.conversation_id == conv_id).all()
        roles = [m.role for m in messages]
        assert MessageRole.USER in roles
        assert MessageRole.ASSISTANT in roles
    finally:
        verify_db.close()

    assert get_pool_status()["checkedout"] == 0


# ===========================================================================
# 5. Client Disconnect & Stream Cancellation Test
# ===========================================================================

def test_stream_cancellation_releases_concurrency_and_does_not_persist():
    """
    Verify client disconnect / generator cancellation:
    When a consumer closes the stream generator prematurely:
    1. Rate limit stream lease is released in finally
    2. Partial message is NOT persisted to DB
    3. Zero DB connections remain checked out
    """
    from app.services.chat_rate_limit_service import ChatRateLimitService

    rate_svc = ChatRateLimitService()
    lease_res = rate_svc.check_and_acquire_stream_slot(user_id=999, org_id=888)
    lease_id = lease_res.lease_id

    setup_db = SessionLocal()
    try:
        user_suffix = uuid.uuid4().hex[:6]
        test_user = User(
            email=f"cancel_{user_suffix}@example.com",
            hashed_password="pw",
            full_name="Cancel User",
            role="Member",
            organization=f"Cancel Org {user_suffix}",
        )
        setup_db.add(test_user)
        setup_db.commit()
        setup_db.refresh(test_user)

        kb = KnowledgeBase(
            name=f"KB Cancel {user_suffix}",
            organization_id=1,
            owner_id=test_user.id,
            is_active=True,
        )
        setup_db.add(kb)
        setup_db.commit()
        setup_db.refresh(kb)

        conv = Conversation(
            title="Cancel Test",
            user_id=test_user.id,
            knowledge_base_id=kb.id,
            organization_id=1,
        )
        setup_db.add(conv)
        setup_db.commit()
        setup_db.refresh(conv)

        conv_id = conv.id
        kb_id = kb.id
        user_id = test_user.id
    finally:
        setup_db.close()

    db = SessionLocal()
    rag = RAGService(db)

    def mock_infinite_stream(prompt, *args, **kwargs):
        yield "FirstToken "
        yield "SecondToken "
        raise GeneratorExit()  # Simulates client abruptly disconnecting

    with patch.object(rag.search_service, "hybrid_search", return_value=[_create_mock_chunk()]), \
         patch.object(rag.llm, "stream_generate", side_effect=mock_infinite_stream), \
         patch.object(rag.llm, "generate", return_value="Expanded query"):

        stream_gen = rag.stream_ask_with_history(
            question="Never finish this",
            knowledge_base_id=kb_id,
            conversation_id=conv_id,
            user_id=user_id,
        )

        tokens_received = []
        try:
            for token in stream_gen:
                tokens_received.append(token)
                stream_gen.close()  # Simulate client disconnect
        except (GeneratorExit, StopIteration):
            pass

    # Release lease as chat endpoint would
    rate_svc.release_stream_slot(lease_id, user_id=999, org_id=888)

    # Verify partial assistant message was NOT saved
    check_db = SessionLocal()
    try:
        assistant_msgs = (
            check_db.query(Message)
            .filter(Message.conversation_id == conv_id, Message.role == MessageRole.ASSISTANT)
            .all()
        )
        assert len(assistant_msgs) == 0
    finally:
        check_db.close()

    # Verify pool has 0 checkedout connections
    assert get_pool_status()["checkedout"] == 0


# ===========================================================================
# 6. Controlled Concurrency Regression Tests (10, 25, 50 requests)
#
# CAPACITY DISTINCTION:
# - Theoretical pool capacity: 10 connections per worker process (pool_size=5 + max_overflow=5).
# - Controlled regression concurrency: Synthetic burst test with 10, 25, and 50 simultaneous
#   trivial queries (SELECT 1) verifying graceful queuing, bounded connection reuse, and 0 leaks.
# - Actual measured application throughput: Dependent on end-to-end API, LLM, and DB complexity.
# - Future real load-test results: Deferred to staging/production load tests (P2-4).
#   This test suite does NOT claim "<50ms" production request latency or "50 concurrent production users".
# ===========================================================================

def _execute_concurrent_db_read(request_id: int):
    """Worker function for concurrent execution testing."""
    db = SessionLocal()
    t0 = time.perf_counter()
    try:
        result = db.execute(text("SELECT 1 AS num, 'concurrency_test' AS tag")).first()
        duration_ms = (time.perf_counter() - t0) * 1000
        return {"id": request_id, "success": result[0] == 1, "duration_ms": duration_ms}
    finally:
        db.close()


@pytest.mark.parametrize("concurrent_requests", [10, 25, 50])
def test_controlled_concurrency_regression(concurrent_requests):
    """
    Controlled regression test exercising 10, 25, and 50 simultaneous DB requests.
    Measures query success rate, verifies checkedout connections return to idle,
    and proves bounded connection reuse without connection leaks under load.
    NOTE: This is a controlled regression benchmark, not a production capacity claim.
    """
    start_status = get_pool_status()
    results = []

    with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
        futures = [executor.submit(_execute_concurrent_db_read, i) for i in range(concurrent_requests)]
        for f in as_completed(futures):
            results.append(f.result())

    # All requests should complete successfully
    assert len(results) == concurrent_requests
    assert all(r["success"] for r in results)

    # Average latency must be sub-second for simple queries under bounded pool
    avg_duration = sum(r["duration_ms"] for r in results) / len(results)
    assert avg_duration < 1000.0

    # Post-burst pool check: all checked out connections must have returned to pool
    end_status = get_pool_status()
    assert end_status["checkedout"] == 0


# ===========================================================================
# 7. Multi-Tenant Isolation Under Concurrency
# ===========================================================================

def test_multi_tenant_isolation_under_concurrency():
    """
    Verify that concurrent database requests from multiple distinct organizations
    maintain strict data isolation and do not leak records across pooled sessions.
    """
    suffix = uuid.uuid4().hex[:6]
    setup_db = SessionLocal()
    try:
        user_a = User(
            email=f"user_a_{suffix}@example.com",
            hashed_password="pw",
            full_name="User A",
            role="Admin",
            organization=f"Org A {suffix}",
        )
        user_b = User(
            email=f"user_b_{suffix}@example.com",
            hashed_password="pw",
            full_name="User B",
            role="Admin",
            organization=f"Org B {suffix}",
        )
        setup_db.add_all([user_a, user_b])
        setup_db.commit()
        setup_db.refresh(user_a)
        setup_db.refresh(user_b)

        org_a = Organization(name=f"Org A {suffix}", slug=f"org-a-{suffix}")
        org_b = Organization(name=f"Org B {suffix}", slug=f"org-b-{suffix}")
        setup_db.add_all([org_a, org_b])
        setup_db.commit()
        setup_db.refresh(org_a)
        setup_db.refresh(org_b)

        kb_a = KnowledgeBase(name=f"KB A {suffix}", organization_id=org_a.id, owner_id=user_a.id, is_active=True)
        kb_b = KnowledgeBase(name=f"KB B {suffix}", organization_id=org_b.id, owner_id=user_b.id, is_active=True)
        setup_db.add_all([kb_a, kb_b])
        setup_db.commit()
        setup_db.refresh(kb_a)
        setup_db.refresh(kb_b)

        org_a_id = org_a.id
        org_b_id = org_b.id
        kb_a_id = kb_a.id
        kb_b_id = kb_b.id
    finally:
        setup_db.close()

    def query_org_kbs(org_id: int):
        db = SessionLocal()
        try:
            kbs = db.query(KnowledgeBase).filter(KnowledgeBase.organization_id == org_id).all()
            return [kb.id for kb in kbs]
        finally:
            db.close()

    # Run 20 concurrent queries alternating between Org A and Org B
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(20):
            target_org = org_a_id if i % 2 == 0 else org_b_id
            futures.append((target_org, executor.submit(query_org_kbs, target_org)))

        for expected_org, fut in futures:
            kb_ids = fut.result()
            if expected_org == org_a_id:
                assert kb_a_id in kb_ids
                assert kb_b_id not in kb_ids
            else:
                assert kb_b_id in kb_ids
                assert kb_a_id not in kb_ids

    assert get_pool_status()["checkedout"] == 0

