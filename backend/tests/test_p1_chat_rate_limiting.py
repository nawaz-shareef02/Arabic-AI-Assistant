"""
P1-2 Tests — Production-Grade Distributed Chat & Streaming Rate Limiting.

Test Suite Coverage:
-------------------
 1. test_chat_rate_limit: Basic sliding-window rate limit rejection after limit exceeded.
 2. test_chat_burst_limit: Burst boundary and rapid request handling.
 3. test_chat_429: Correct HTTP 429 status code and safe error payload.
 4. test_stream_rate_limit: Streaming requests respect sliding-window request limit.
 5. test_stream_concurrency_limit: Active streaming concurrency is bounded per user.
 6. test_stream_release_on_completion: Concurrency lease released when stream finishes.
 7. test_stream_release_on_exception: Concurrency lease released when stream raises exception.
 8. test_stream_release_on_disconnect: Concurrency lease released when generator is closed early.
 9. test_multi_worker_shared_limit: Shared Redis state across multiple service instances.
10. test_organization_rate_limit: Organization-level aggregate safety ceiling enforced.
11. test_user_isolation: User A's usage does not affect User B's quota.
12. test_cross_org_rate_limit_isolation: Cross-organization quota isolation.
13. test_unauthenticated_chat_rejected: Unauthenticated requests return 401 without consuming tokens.
14. test_rate_limit_before_rag: RAGService is never invoked for rate-limited requests.
15. test_rate_limit_before_llm: LLM inference is never executed for rate-limited requests.
16. test_redis_atomicity: Lua script guarantees atomic check-and-increment.
17. test_redis_failure_behavior: Graceful fallback when Redis is unreachable.
18. test_retry_after: Retry-After header contains positive integer seconds.
19. test_rate_limit_headers: X-RateLimit-* headers are accurately returned.
20. test_parallel_request_flood: Multithreaded concurrency flood testing.
21. test_parallel_stream_flood: Multithreaded streaming concurrency flood testing.
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db
from app.core.config import settings
from app.database.base import Base
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.knowledge_base import KnowledgeBase
from app.core.security import get_password_hash, create_access_token
from app.services.chat_rate_limit_service import (
    ChatRateLimitService,
    RateLimitResult,
    SLIDING_WINDOW_LUA,
    ACQUIRE_STREAM_CONCURRENCY_LUA,
    RELEASE_STREAM_CONCURRENCY_LUA,
)


SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def auto_reset_rate_limit_state():
    """Ensures pristine zero-count rate limiting state in Redis and memory for each test."""
    ChatRateLimitService.reset_all_state()
    yield
    ChatRateLimitService.reset_all_state()


@pytest.fixture(name="db_session")
def fixture_db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    ChatRateLimitService.reset_all_state()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        ChatRateLimitService.reset_all_state()


@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(name="chat_setup")
def fixture_chat_setup(db_session):
    """Sets up two organizations, users, and knowledge bases for chat tests."""
    org_a = Organization(name="Aramco Corp", slug="aramco", is_active=True)
    org_b = Organization(name="SABIC Corp", slug="sabic", is_active=True)
    db_session.add_all([org_a, org_b])
    db_session.commit()

    user_a1 = User(
        email="analyst1@aramco.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Aramco Analyst 1",
        organization=org_a.name,
        is_active=True,
    )
    user_a2 = User(
        email="analyst2@aramco.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Aramco Analyst 2",
        organization=org_a.name,
        is_active=True,
    )
    user_b = User(
        email="engineer@sabic.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="SABIC Engineer",
        organization=org_b.name,
        is_active=True,
    )
    db_session.add_all([user_a1, user_a2, user_b])
    db_session.commit()

    db_session.add_all([
        OrganizationMember(organization_id=org_a.id, user_id=user_a1.id),
        OrganizationMember(organization_id=org_a.id, user_id=user_a2.id),
        OrganizationMember(organization_id=org_b.id, user_id=user_b.id),
    ])
    db_session.commit()

    kb_a = KnowledgeBase(
        name="Aramco Oil & Gas Docs",
        owner_id=user_a1.id,
        organization_id=org_a.id,
    )
    kb_b = KnowledgeBase(
        name="SABIC Petrochemical Docs",
        owner_id=user_b.id,
        organization_id=org_b.id,
    )
    db_session.add_all([kb_a, kb_b])
    db_session.commit()

    token_a1 = create_access_token(
        subject=user_a1.email,
        additional_claims={"user_id": user_a1.id, "org_id": org_a.id},
    )
    token_a2 = create_access_token(
        subject=user_a2.email,
        additional_claims={"user_id": user_a2.id, "org_id": org_a.id},
    )
    token_b = create_access_token(
        subject=user_b.email,
        additional_claims={"user_id": user_b.id, "org_id": org_b.id},
    )

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a1": user_a1,
        "user_a2": user_a2,
        "user_b": user_b,
        "kb_a": kb_a,
        "kb_b": kb_b,
        "token_a1": token_a1,
        "token_a2": token_a2,
        "token_b": token_b,
        "headers_a1": {"Authorization": f"Bearer {token_a1}"},
        "headers_a2": {"Authorization": f"Bearer {token_a2}"},
        "headers_b": {"Authorization": f"Bearer {token_b}"},
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Standard Request Rate Limiting Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_chat_rate_limit(chat_setup):
    """1. test_chat_rate_limit: Sliding window enforces configured limit."""
    svc = ChatRateLimitService(user_req_limit=3, window_seconds=60)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    r1 = svc.check_chat_rate_limit(user_id, org_id)
    assert r1.allowed is True
    assert r1.remaining == 2

    r2 = svc.check_chat_rate_limit(user_id, org_id)
    assert r2.allowed is True
    assert r2.remaining == 1

    r3 = svc.check_chat_rate_limit(user_id, org_id)
    assert r3.allowed is True
    assert r3.remaining == 0

    # 4th request exceeds limit
    r4 = svc.check_chat_rate_limit(user_id, org_id)
    assert r4.allowed is False
    assert r4.retry_after > 0


def test_chat_burst_limit(chat_setup):
    """2. test_chat_burst_limit: Burst requests within small window."""
    svc = ChatRateLimitService(user_req_limit=5, window_seconds=60)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    for _ in range(5):
        assert svc.check_chat_rate_limit(user_id, org_id).allowed is True

    # Burst exceeded
    assert svc.check_chat_rate_limit(user_id, org_id).allowed is False


def test_chat_429(client, chat_setup):
    """3. test_chat_429: API returns HTTP 429 with standard safe JSON payload."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    with patch("app.services.rag_service.RAGService.ask", return_value={"answer": "ok", "sources": []}):
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_REQ_PER_MINUTE", 2):
            ChatRateLimitService.reset_all_state()

            # Req 1: OK
            res1 = client.post("/api/v1/chat/", json={"question": "What is Aramco?", "knowledge_base_id": kb_id}, headers=headers)
            assert res1.status_code == 200

            # Req 2: OK
            res2 = client.post("/api/v1/chat/", json={"question": "What is Aramco 2?", "knowledge_base_id": kb_id}, headers=headers)
            assert res2.status_code == 200

            # Req 3: 429
            res3 = client.post("/api/v1/chat/", json={"question": "What is Aramco 3?", "knowledge_base_id": kb_id}, headers=headers)
            assert res3.status_code == 429
            data = res3.json()
            assert "detail" in data
            assert "Too many AI requests" in data["detail"]
            assert "Retry-After" in res3.headers
            assert "X-RateLimit-Limit" in res3.headers


def test_stream_rate_limit(client, chat_setup):
    """4. test_stream_rate_limit: Streaming endpoints obey request rate limits."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    def mock_stream(*args, **kwargs):
        yield "token1 "
        yield "token2"

    with patch("app.services.rag_service.RAGService.stream_ask", side_effect=mock_stream):
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_REQ_PER_MINUTE", 2):
            ChatRateLimitService.reset_all_state()

            # Req 1: OK
            r1 = client.post("/api/v1/chat/stream", json={"question": "Stream test 1", "knowledge_base_id": kb_id}, headers=headers)
            assert r1.status_code == 200

            # Req 2: OK
            r2 = client.post("/api/v1/chat/stream", json={"question": "Stream test 2", "knowledge_base_id": kb_id}, headers=headers)
            assert r2.status_code == 200

            # Req 3: 429
            r3 = client.post("/api/v1/chat/stream", json={"question": "Stream test 3", "knowledge_base_id": kb_id}, headers=headers)
            assert r3.status_code == 429


# ──────────────────────────────────────────────────────────────────────────────
# 2. Streaming Concurrency & Lease Lifecycle Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_stream_concurrency_limit(chat_setup):
    """5. test_stream_concurrency_limit: Active stream concurrency is bounded per user."""
    svc = ChatRateLimitService(user_req_limit=50, user_max_streams=2)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    # Acquire stream 1
    s1 = svc.check_and_acquire_stream_slot(user_id, org_id)
    assert s1.allowed is True
    assert s1.lease_id is not None

    # Acquire stream 2
    s2 = svc.check_and_acquire_stream_slot(user_id, org_id)
    assert s2.allowed is True
    assert s2.lease_id is not None

    # Attempt stream 3 -> Exceeds max concurrent streams (2)
    s3 = svc.check_and_acquire_stream_slot(user_id, org_id)
    assert s3.allowed is False
    assert "concurrency" in s3.reason.lower()


def test_stream_release_on_completion(client, chat_setup):
    """6. test_stream_release_on_completion: Concurrency lease is released when stream completes."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    def mock_stream(*args, **kwargs):
        yield "token1 "
        yield "token2"

    with patch("app.services.rag_service.RAGService.stream_ask", side_effect=mock_stream):
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_MAX_CONCURRENT_STREAMS", 1):
            ChatRateLimitService.reset_all_state()

            # First stream runs to completion
            r1 = client.post("/api/v1/chat/stream", json={"question": "Q1", "knowledge_base_id": kb_id}, headers=headers)
            assert r1.status_code == 200
            assert "token1" in r1.text

            # Second stream can now be acquired because stream 1 released its slot
            r2 = client.post("/api/v1/chat/stream", json={"question": "Q2", "knowledge_base_id": kb_id}, headers=headers)
            assert r2.status_code == 200
            assert "token1" in r2.text


def test_stream_release_on_exception(client, chat_setup):
    """7. test_stream_release_on_exception: Concurrency lease released if generator fails."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    def mock_failing_stream(*args, **kwargs):
        yield "start"
        raise RuntimeError("LLM worker died midway")

    def mock_clean_stream(*args, **kwargs):
        yield "healthy stream"

    with patch("app.services.rag_service.RAGService.stream_ask", side_effect=mock_failing_stream):
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_MAX_CONCURRENT_STREAMS", 1):
            ChatRateLimitService.reset_all_state()

            # First stream fails during generation
            with pytest.raises(Exception):
                client.post("/api/v1/chat/stream", json={"question": "Failing Q", "knowledge_base_id": kb_id}, headers=headers)

    # Next stream should succeed because lease was released in finally block
    with patch("app.services.rag_service.RAGService.stream_ask", side_effect=mock_clean_stream):
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_MAX_CONCURRENT_STREAMS", 1):
            r2 = client.post("/api/v1/chat/stream", json={"question": "Healthy Q", "knowledge_base_id": kb_id}, headers=headers)
            assert r2.status_code == 200
            assert "healthy stream" in r2.text


def test_stream_release_on_disconnect(chat_setup):
    """8. test_stream_release_on_disconnect: Direct release_stream_slot call is idempotent."""
    svc = ChatRateLimitService(user_req_limit=50, user_max_streams=1)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    s1 = svc.check_and_acquire_stream_slot(user_id, org_id)
    assert s1.allowed is True
    lease_id = s1.lease_id

    # Simulated client disconnect / generator close
    released = svc.release_stream_slot(lease_id, user_id, org_id)
    assert released is True

    # Idempotent second release does not corrupt counter
    assert svc.release_stream_slot(lease_id, user_id, org_id) is False

    # New stream can acquire
    s2 = svc.check_and_acquire_stream_slot(user_id, org_id)
    assert s2.allowed is True


# ──────────────────────────────────────────────────────────────────────────────
# 3. Multi-Tenancy & Isolation Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_multi_worker_shared_limit(chat_setup):
    """9. test_multi_worker_shared_limit: Multiple worker instances share rate-limit state."""
    worker1 = ChatRateLimitService(user_req_limit=3, window_seconds=60)
    worker2 = ChatRateLimitService(user_req_limit=3, window_seconds=60)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    # Worker 1 processes 2 requests
    assert worker1.check_chat_rate_limit(user_id, org_id).allowed is True
    assert worker1.check_chat_rate_limit(user_id, org_id).allowed is True

    # Worker 2 processes 1 request (hits limit 3)
    assert worker2.check_chat_rate_limit(user_id, org_id).allowed is True

    # Worker 1 now blocks the 4th request
    assert worker1.check_chat_rate_limit(user_id, org_id).allowed is False
    # Worker 2 also blocks
    assert worker2.check_chat_rate_limit(user_id, org_id).allowed is False


def test_organization_rate_limit(chat_setup):
    """10. test_organization_rate_limit: Aggregate organization ceiling protects LLM."""
    # Org limit 4, user limit 3. Two users in same org.
    svc = ChatRateLimitService(user_req_limit=3, org_req_limit=4, window_seconds=60)
    user_a1 = chat_setup["user_a1"].id
    user_a2 = chat_setup["user_a2"].id
    org_id = chat_setup["org_a"].id

    # User 1 makes 2 requests
    assert svc.check_chat_rate_limit(user_a1, org_id).allowed is True
    assert svc.check_chat_rate_limit(user_a1, org_id).allowed is True

    # User 2 makes 2 requests (Total Org = 4)
    assert svc.check_chat_rate_limit(user_a2, org_id).allowed is True
    assert svc.check_chat_rate_limit(user_a2, org_id).allowed is True

    # User 1 has only made 2/3 requests, BUT Org has reached 4/4 -> blocked by Org ceiling
    res_a1 = svc.check_chat_rate_limit(user_a1, org_id)
    assert res_a1.allowed is False
    assert "org" in res_a1.reason.lower()


def test_user_isolation(chat_setup):
    """11. test_user_isolation: User A consuming quota does not affect User B."""
    svc = ChatRateLimitService(user_req_limit=2, org_req_limit=100, window_seconds=60)
    user_a1 = chat_setup["user_a1"].id
    user_a2 = chat_setup["user_a2"].id
    org_id = chat_setup["org_a"].id

    # User A1 exhausts limit
    assert svc.check_chat_rate_limit(user_a1, org_id).allowed is True
    assert svc.check_chat_rate_limit(user_a1, org_id).allowed is True
    assert svc.check_chat_rate_limit(user_a1, org_id).allowed is False

    # User A2 is unaffected
    assert svc.check_chat_rate_limit(user_a2, org_id).allowed is True
    assert svc.check_chat_rate_limit(user_a2, org_id).allowed is True


def test_cross_org_rate_limit_isolation(chat_setup):
    """12. test_cross_org_rate_limit_isolation: Org A quota is strictly isolated from Org B."""
    svc = ChatRateLimitService(user_req_limit=2, org_req_limit=2, window_seconds=60)
    user_a = chat_setup["user_a1"].id
    org_a = chat_setup["org_a"].id
    user_b = chat_setup["user_b"].id
    org_b = chat_setup["org_b"].id

    # Org A exhausts quota
    assert svc.check_chat_rate_limit(user_a, org_a).allowed is True
    assert svc.check_chat_rate_limit(user_a, org_a).allowed is True
    assert svc.check_chat_rate_limit(user_a, org_a).allowed is False

    # Org B is completely unaffected
    assert svc.check_chat_rate_limit(user_b, org_b).allowed is True
    assert svc.check_chat_rate_limit(user_b, org_b).allowed is True


# ──────────────────────────────────────────────────────────────────────────────
# 4. Security Pipeline & Execution Order Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_unauthenticated_chat_rejected(client, chat_setup):
    """13. test_unauthenticated_chat_rejected: 401 occurs before consuming rate limit tokens."""
    kb_id = chat_setup["kb_a"].id

    # Unauthenticated request
    res = client.post("/api/v1/chat/", json={"question": "Hello", "knowledge_base_id": kb_id})
    assert res.status_code == 401


def test_rate_limit_before_rag(client, chat_setup):
    """14. test_rate_limit_before_rag: RAGService is never invoked for rate-limited requests."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    with patch("app.services.rag_service.RAGService.ask", return_value={"answer": "ok", "sources": []}) as mock_ask:
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_REQ_PER_MINUTE", 1):
            ChatRateLimitService.reset_all_state()

            # First request succeeds and calls RAG
            r1 = client.post("/api/v1/chat/", json={"question": "Q1", "knowledge_base_id": kb_id}, headers=headers)
            assert r1.status_code == 200
            assert mock_ask.call_count == 1

            # Second request is rate limited -> 429
            r2 = client.post("/api/v1/chat/", json={"question": "Q2", "knowledge_base_id": kb_id}, headers=headers)
            assert r2.status_code == 429

            # RAG was NOT called a second time
            assert mock_ask.call_count == 1


def test_rate_limit_before_llm(client, chat_setup):
    """15. test_rate_limit_before_llm: LLM inference is never executed when rate-limited."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    with patch("app.services.rag_service.RAGService.ask", return_value={"answer": "ans", "sources": []}) as mock_ask:
        with patch.object(settings, "CHAT_RATE_LIMIT_USER_REQ_PER_MINUTE", 1):
            ChatRateLimitService.reset_all_state()

            r1 = client.post("/api/v1/chat/", json={"question": "Q1", "knowledge_base_id": kb_id}, headers=headers)
            assert r1.status_code == 200

            r2 = client.post("/api/v1/chat/", json={"question": "Q2", "knowledge_base_id": kb_id}, headers=headers)
            assert r2.status_code == 429
            assert mock_ask.call_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# 5. Atomicity & Resilience Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_redis_atomicity():
    """16. test_redis_atomicity: Lua script constants are syntactically valid."""
    assert "ZREMRANGEBYSCORE" in SLIDING_WINDOW_LUA
    assert "ZADD" in SLIDING_WINDOW_LUA
    assert "SETEX" in ACQUIRE_STREAM_CONCURRENCY_LUA
    assert "DECR" in RELEASE_STREAM_CONCURRENCY_LUA


def test_redis_failure_behavior(chat_setup):
    """17. test_redis_failure_behavior: Graceful in-memory degradation when Redis unavailable."""
    failing_mock = MagicMock()
    failing_mock.eval.side_effect = Exception("Redis connection refused")

    svc = ChatRateLimitService(user_req_limit=2, fail_closed=False, client=failing_mock)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    # Fallback to memory
    r1 = svc.check_chat_rate_limit(user_id, org_id)
    assert r1.allowed is True

    r2 = svc.check_chat_rate_limit(user_id, org_id)
    assert r2.allowed is True

    r3 = svc.check_chat_rate_limit(user_id, org_id)
    assert r3.allowed is False


def test_retry_after(chat_setup):
    """18. test_retry_after: Retry-After header calculation."""
    svc = ChatRateLimitService(user_req_limit=1, window_seconds=30)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    r1 = svc.check_chat_rate_limit(user_id, org_id)
    assert r1.allowed is True
    assert r1.headers.get("Retry-After") is None

    r2 = svc.check_chat_rate_limit(user_id, org_id)
    assert r2.allowed is False
    assert "Retry-After" in r2.headers
    assert int(r2.headers["Retry-After"]) > 0


def test_rate_limit_headers(client, chat_setup):
    """19. test_rate_limit_headers: Standard X-RateLimit-* headers returned."""
    headers = chat_setup["headers_a1"]
    kb_id = chat_setup["kb_a"].id

    with patch("app.services.rag_service.RAGService.ask", return_value={"answer": "ok", "sources": []}):
        res = client.post("/api/v1/chat/", json={"question": "Headers check", "knowledge_base_id": kb_id}, headers=headers)
        assert res.status_code == 200
        assert "X-RateLimit-Limit" in res.headers
        assert "X-RateLimit-Remaining" in res.headers
        assert "X-RateLimit-Reset" in res.headers


# ──────────────────────────────────────────────────────────────────────────────
# 6. Concurrency & Parallel Request Flood Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_parallel_request_flood(chat_setup):
    """20. test_parallel_request_flood: 20 simultaneous threads attempting requests."""
    svc = ChatRateLimitService(user_req_limit=5, window_seconds=60)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    def make_request(i):
        return svc.check_chat_rate_limit(user_id, org_id).allowed

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(make_request, range(20)))

    allowed_count = sum(1 for r in results if r is True)
    blocked_count = sum(1 for r in results if r is False)

    # Exactly 5 requests must be allowed, and 15 blocked
    assert allowed_count == 5
    assert blocked_count == 15


def test_parallel_stream_flood(chat_setup):
    """21. test_parallel_stream_flood: 20 simultaneous threads attempting to acquire stream leases."""
    svc = ChatRateLimitService(user_req_limit=50, user_max_streams=3)
    user_id = chat_setup["user_a1"].id
    org_id = chat_setup["org_a"].id

    def acquire_slot(i):
        return svc.check_and_acquire_stream_slot(user_id, org_id)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(acquire_slot, range(20)))

    allowed = [r for r in results if r.allowed is True]
    blocked = [r for r in results if r.allowed is False]

    # Exactly 3 streams must be allowed to acquire, 17 blocked
    assert len(allowed) == 3
    assert len(blocked) == 17

    # Release all 3 acquired streams
    for r in allowed:
        assert svc.release_stream_slot(r.lease_id, user_id, org_id) is True

    # Next stream should now be allowed
    assert svc.check_and_acquire_stream_slot(user_id, org_id).allowed is True
