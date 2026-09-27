"""
test_ai8_prec_reconciliation.py - AI-8 Pre-C Architecture Reconciliation Tests

Tests:
  1. ask_with_history() uses GenerationResult.token_usage (not word count)
  2. stream_ask_with_history() uses StreamingResult.token_usage (not word count)
  3. _persist_assistant_message stores prompt+completion+total; None->0
  4. delete_document_vectors fails closed when organization_id is None
  5. QueryExpansionService uses shared module-level Redis (not per-instance)
  6. update_quotas uses partial update semantics (leaves unset fields unchanged)
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker
from unittest.mock import MagicMock, patch

from app.database.base import Base
from app.services.llm.base import GenerationResult, StreamingResult, TokenUsage

# Import all models so Base.metadata is fully populated before create_all().
# Without this, create_all() creates zero tables because models aren't registered.
import app.models.organization  # noqa: F401
import app.models.user  # noqa: F401
import app.models.knowledge_base  # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.message  # noqa: F401
import app.models.chunk  # noqa: F401
import app.models.document  # noqa: F401
import app.models.role  # noqa: F401
import app.models.workspace  # noqa: F401


@pytest.fixture
def db_session():
    """Isolated in-memory SQLite DB per test (matching Phase B test pattern)."""
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    _Session = sessionmaker(bind=engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()


def _make_conv(db_session):
    """Insert minimal Org/User/KB/Conversation rows for FK satisfaction."""
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.knowledge_base import KnowledgeBase
    from app.models.conversation import Conversation
    import uuid as _uuid

    org = Organization(name="O", slug=f"s-{_uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    # User model has a NOT NULL 'organization' (legacy) column — supply it.
    user = User(
        email=f"{_uuid.uuid4().hex[:8]}@x.com",
        hashed_password="x",
        full_name="U",
        is_active=True,
        organization=org.name,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    kb = KnowledgeBase(name="K", organization_id=org.id, owner_id=user.id, is_active=True)
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)

    conv = Conversation(organization_id=org.id, knowledge_base_id=kb.id, user_id=user.id)
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


def _make_rag(db):
    """Construct RAGService.__new__ with all heavy singletons bypassed."""
    from app.services.rag_service import RAGService
    with patch("app.services.rag_service.SearchService"), \
         patch("app.services.rag_service.LLMFactory"), \
         patch("app.services.rag_service.QueryExpansionService"), \
         patch("app.services.rag_service.get_reranker"):
        svc = RAGService.__new__(RAGService)
        svc.db = db
        return svc


# ============================================================
# 3 — _persist_assistant_message token storage contract
# ============================================================

class TestPersistAssistantMessage:

    def test_stores_prompt_completion_and_total(self, db_session):
        """Both prompt_tokens and completion_tokens are stored; total=sum."""
        from app.models.message import Message
        svc = _make_rag(db_session)
        conv = _make_conv(db_session)
        # Capture the int PK now — _persist_assistant_message closes the session
        # (via db.close() in its finally block), which would detach conv.
        conv_id = conv.id

        # SessionLocal is a deferred local import inside _persist_assistant_message.
        # Patch it at its canonical module path.
        with patch("app.database.session.SessionLocal", return_value=db_session):
            svc._persist_assistant_message(
                conversation_id=conv_id,
                content="Answer.",
                citations=None,
                completion_tokens=42,
                prompt_tokens=17,
            )

        msg = db_session.query(Message).filter(
            Message.conversation_id == conv_id
        ).first()
        assert msg is not None, "Message was not persisted"
        assert msg.completion_tokens == 42
        assert msg.prompt_tokens == 17
        assert msg.total_tokens == 59  # 42 + 17

    def test_none_coerced_to_zero(self, db_session):
        """None token metadata (unavailable) is coerced to 0, not stored as NULL."""
        from app.models.message import Message
        svc = _make_rag(db_session)
        conv = _make_conv(db_session)
        conv_id = conv.id

        with patch("app.database.session.SessionLocal", return_value=db_session):
            svc._persist_assistant_message(
                conversation_id=conv_id,
                content="Partial.",
                citations=None,
                completion_tokens=None,
                prompt_tokens=None,
            )

        msg = db_session.query(Message).filter(
            Message.conversation_id == conv_id
        ).first()
        assert msg is not None, "Message was not persisted"
        assert msg.completion_tokens == 0
        assert msg.prompt_tokens == 0
        assert msg.total_tokens == 0


# ============================================================
# 4 — QdrantService delete fail-closed
# ============================================================

class TestQdrantDeleteFailClosed:

    def _qdrant(self):
        from app.services.qdrant_service import QdrantService
        svc = QdrantService.__new__(QdrantService)
        svc.collection_name = "col"
        QdrantService._client = MagicMock()
        svc.embedding_service = MagicMock()
        return svc

    def test_raises_when_org_id_none(self):
        """organization_id=None must raise ValueError (fail-closed)."""
        with pytest.raises(ValueError, match="organization_id"):
            self._qdrant().delete_document_vectors(
                parsed_document_id=1, organization_id=None
            )

    def test_succeeds_with_org_id(self):
        """Valid org_id must not raise and must return True."""
        svc = self._qdrant()
        result = svc.delete_document_vectors(
            parsed_document_id=1, organization_id=5, knowledge_base_id=2
        )
        assert result is True

    def test_succeeds_without_kb_id(self):
        """organization_id is required; knowledge_base_id is optional."""
        svc = self._qdrant()
        result = svc.delete_document_vectors(
            parsed_document_id=1, organization_id=5
        )
        assert result is True

    def test_org_id_in_qdrant_filter(self):
        """organization_id must appear in the Qdrant must[] filter payload."""
        svc = self._qdrant()
        svc.delete_document_vectors(
            parsed_document_id=1, organization_id=42, knowledge_base_id=3
        )
        call_kwargs = svc.client.delete.call_args[1]
        must = call_kwargs["points_selector"]["filter"]["must"]
        keys = {c["key"] for c in must}
        assert "organization_id" in keys
        org_val = next(c["match"]["value"] for c in must if c["key"] == "organization_id")
        assert org_val == 42

    def test_missing_kb_id_no_kb_filter(self):
        """knowledge_base_id=None must not appear in Qdrant filter."""
        svc = self._qdrant()
        svc.delete_document_vectors(parsed_document_id=1, organization_id=42)
        call_kwargs = svc.client.delete.call_args[1]
        must = call_kwargs["points_selector"]["filter"]["must"]
        keys = {c["key"] for c in must}
        assert "knowledge_base_id" not in keys


# ============================================================
# 5 — QueryExpansionService shared Redis lifecycle
# ============================================================

class TestQueryExpansionSharedRedis:

    def test_instances_share_same_redis_object(self):
        """Multiple QueryExpansionService instances must share one Redis client."""
        import app.services.query_expansion_service as m
        m._shared_redis = None
        m._redis_init_attempted = False

        mock_r = MagicMock()
        mock_r.ping.return_value = True

        with patch("app.services.query_expansion_service.redis") as mock_mod:
            mock_mod.Redis.from_url.return_value = mock_r
            from app.services.query_expansion_service import QueryExpansionService
            s1 = QueryExpansionService()
            s2 = QueryExpansionService()

        assert s1._redis is s2._redis

    def test_from_url_called_once(self):
        """redis.Redis.from_url must be called exactly once (not per-instance)."""
        import app.services.query_expansion_service as m
        m._shared_redis = None
        m._redis_init_attempted = False

        mock_r = MagicMock()
        mock_r.ping.return_value = True

        with patch("app.services.query_expansion_service.redis") as mock_mod:
            mock_mod.Redis.from_url.return_value = mock_r
            from app.services.query_expansion_service import QueryExpansionService
            QueryExpansionService()
            QueryExpansionService()
            QueryExpansionService()

        assert mock_mod.Redis.from_url.call_count == 1

    def test_redis_unavailable_degrades_gracefully(self):
        """Redis failure must not raise on instantiation; self._redis set to None."""
        import app.services.query_expansion_service as m
        m._shared_redis = None
        m._redis_init_attempted = False

        with patch("app.services.query_expansion_service.redis") as mock_mod:
            mock_mod.Redis.from_url.side_effect = Exception("Connection refused")
            from app.services.query_expansion_service import QueryExpansionService
            svc = QueryExpansionService()

        assert svc._redis is None


# ============================================================
# 6 — update_quotas partial update semantics
# ============================================================

class TestUpdateQuotasPartial:

    def test_single_field_preserves_others(self, db_session: Session):
        """Updating only monthly_token_budget must not reset max_storage_mb or max_documents."""
        from app.repositories.organization_repository import OrganizationRepository
        from app.models.organization import Organization
        import uuid as _uuid

        org = Organization(
            name="Q1",
            slug=f"q1-{_uuid.uuid4().hex[:6]}",
            is_active=True,
            monthly_token_budget=1_000_000,
            max_storage_mb=500,
            max_documents=200,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        updated = OrganizationRepository(db_session).update_quotas(
            org_id=org.id,
            monthly_token_budget=2_000_000,
            # max_storage_mb and max_documents intentionally omitted
        )

        assert updated is not None
        assert updated.monthly_token_budget == 2_000_000
        assert updated.max_storage_mb == 500    # preserved
        assert updated.max_documents == 200     # preserved

    def test_all_fields_updated(self, db_session: Session):
        """When all fields are provided, all three are written."""
        from app.repositories.organization_repository import OrganizationRepository
        from app.models.organization import Organization
        import uuid as _uuid

        org = Organization(
            name="Q2",
            slug=f"q2-{_uuid.uuid4().hex[:6]}",
            is_active=True,
            monthly_token_budget=1,
            max_storage_mb=1,
            max_documents=1,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        updated = OrganizationRepository(db_session).update_quotas(
            org_id=org.id,
            monthly_token_budget=100,
            max_storage_mb=200,
            max_documents=300,
        )

        assert updated.monthly_token_budget == 100
        assert updated.max_storage_mb == 200
        assert updated.max_documents == 300

    def test_nonexistent_org_returns_none(self, db_session: Session):
        """update_quotas returns None for a nonexistent org_id."""
        from app.repositories.organization_repository import OrganizationRepository
        result = OrganizationRepository(db_session).update_quotas(
            org_id=999999, monthly_token_budget=1
        )
        assert result is None


# ============================================================
# 1 — ask_with_history() authoritative token integration
# ============================================================

class TestAskWithHistoryTokenContract:
    """
    Validates that ask_with_history() passes GenerationResult.token_usage
    to _persist_assistant_message, not len(answer.split()) word count.
    Strategy: spy on _persist_assistant_message by replacing it with a
    capture lambda, then assert what tokens were passed.
    """

    def _run(self, gen_result):
        from app.services.rag_service import RAGService

        with patch("app.services.rag_service.SearchService"), \
             patch("app.services.rag_service.LLMFactory") as mock_factory, \
             patch("app.services.rag_service.QueryExpansionService"), \
             patch("app.services.rag_service.get_reranker"), \
             patch("app.services.rag_service.PromptSecurityService"):

            mock_llm = MagicMock()
            mock_llm.generate.return_value = gen_result
            mock_factory.get_provider.return_value = mock_llm

            svc = RAGService(MagicMock())
            svc._msg_repo = MagicMock()
            svc._msg_repo.create.return_value = MagicMock(id=1)
            svc._msg_repo.get_history.return_value = []
            svc._rewriter = MagicMock()
            svc._rewriter.rewrite.return_value = "q"
            svc._expander = MagicMock()
            svc._expander.expand.return_value = "q"
            svc.search_service = MagicMock()
            svc.search_service.hybrid_search.return_value = [
                MagicMock(text="c", score=0.9, chunk_uuid="a", parsed_document_id=1)
            ]
            svc._reranker = MagicMock()
            svc._reranker.rerank.return_value = [
                MagicMock(text="c", score=0.9, chunk_uuid="a", parsed_document_id=1)
            ]
            svc._release_db = MagicMock()

            cap = {}
            svc._persist_assistant_message = lambda **kw: cap.update(kw)

            svc.ask_with_history(
                question="Q?",
                knowledge_base_id=1,
                conversation_id=10,
                user_id=5,
                organization_id=2,
            )

        return cap

    def test_completion_tokens_from_ollama_not_word_count(self):
        """3-word answer; Ollama says 150 tokens — persist 150, not 3."""
        usage = TokenUsage(
            prompt_tokens=45, completion_tokens=150, total_tokens=195,
            is_terminal=True, is_exact=True,
        )
        gen = GenerationResult(text="Yes it does.", token_usage=usage, model="q")
        cap = self._run(gen)
        assert cap.get("completion_tokens") == 150, (
            f"Expected 150 (Ollama token count), got {cap.get('completion_tokens')}"
        )
        assert cap.get("prompt_tokens") == 45

    def test_none_token_usage_propagates_none(self):
        """If GenerationResult.token_usage is None, persist None (coerced to 0 by helper)."""
        gen = GenerationResult(text="A B C.", token_usage=None, model="q")
        cap = self._run(gen)
        assert cap.get("completion_tokens") is None
        assert cap.get("prompt_tokens") is None


# ============================================================
# 2 — stream_ask_with_history() authoritative token integration
# ============================================================

class TestStreamAskWithHistoryTokenContract:
    """
    Validates that stream_ask_with_history() passes StreamingResult.token_usage
    to _persist_assistant_message when is_exact=True, and passes None when
    is_exact=False (not the word count of accumulated_answer).
    """

    def _run(self, stream_result):
        from app.services.rag_service import RAGService

        with patch("app.services.rag_service.SearchService"), \
             patch("app.services.rag_service.LLMFactory") as mock_factory, \
             patch("app.services.rag_service.QueryExpansionService"), \
             patch("app.services.rag_service.get_reranker"), \
             patch("app.services.rag_service.PromptSecurityService"):

            mock_llm = MagicMock()
            mock_llm.stream_generate.return_value = stream_result
            mock_factory.get_provider.return_value = mock_llm

            svc = RAGService(MagicMock())
            svc._msg_repo = MagicMock()
            svc._msg_repo.create.return_value = MagicMock(id=1)
            svc._msg_repo.get_history.return_value = []
            svc._rewriter = MagicMock()
            svc._rewriter.rewrite.return_value = "q"
            svc._expander = MagicMock()
            svc._expander.expand.return_value = "q"
            svc.search_service = MagicMock()
            svc.search_service.hybrid_search.return_value = [
                MagicMock(text="c", score=0.9, chunk_uuid="a", parsed_document_id=1)
            ]
            svc._reranker = MagicMock()
            svc._reranker.rerank.return_value = [
                MagicMock(text="c", score=0.9, chunk_uuid="a", parsed_document_id=1)
            ]
            svc._release_db = MagicMock()

            cap = {}
            svc._persist_assistant_message = lambda **kw: cap.update(kw)

            list(svc.stream_ask_with_history(
                question="Q?",
                knowledge_base_id=1,
                conversation_id=10,
                user_id=5,
                organization_id=2,
            ))

        return cap

    def test_exact_streaming_tokens_stored(self):
        """2 chunks; Ollama says 200 tokens — persist 200, not 2."""
        usage = TokenUsage(
            prompt_tokens=30, completion_tokens=200, total_tokens=230,
            is_terminal=True, is_exact=True,
        )
        stream_res = StreamingResult(
            generator=iter(["word1 ", "word2"]),
            model="q",
            usage_box=[usage],
        )
        cap = self._run(stream_res)
        assert cap.get("completion_tokens") == 200, (
            f"Expected 200 (Ollama exact count), got {cap.get('completion_tokens')}"
        )
        assert cap.get("prompt_tokens") == 30

    def test_inexact_metadata_stores_none(self):
        """When is_exact=False, persist None — not the word count of accumulated text."""
        inexact = TokenUsage(
            prompt_tokens=None, completion_tokens=None, total_tokens=None,
            is_terminal=False, is_exact=False,
        )
        stream_res = StreamingResult(
            generator=iter(["partial answer"]),
            model="q",
            usage_box=[inexact],
        )
        cap = self._run(stream_res)
        # "partial answer" = 2 words; inexact metadata → must be None (not 2)
        assert cap.get("completion_tokens") is None, (
            f"Expected None for inexact metadata, got {cap.get('completion_tokens')}"
        )
        assert cap.get("prompt_tokens") is None

