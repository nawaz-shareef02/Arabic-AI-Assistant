# pyrefly: ignore-file
"""
RAGService — Enterprise Retrieval-Augmented Generation Orchestrator.

Sprint 12 Pipeline
------------------
1. Conversation History (existing)
2. Query Rewriter (existing)
3. Query Expansion (Sprint 12 — with Redis cache)
4. Hybrid Search: Dense + Keyword + RRF (Sprint 12)
5. Optional Re-ranking (Sprint 12 — NoOp default)
6. Prompt Builder (Sprint 12 — enhanced)
7. LLM Generation (existing)
8. Streaming Response (existing)

Sprint 12 Additions:
- QueryExpansionService — bilingual expansion with Redis cache
- Hybrid search via SearchService.hybrid_search()
- RerankerService — pluggable interface (NoOp default)
- RetrievalProfiler — centralized per-stage timing
- Debug diagnostics — chunk-level scores and metadata

Backward Compatibility:
- All 4 existing methods preserved: ask, stream_ask, ask_with_history,
  stream_ask_with_history
- Method signatures unchanged
- Streaming behavior unchanged
- Message persistence logic unchanged
- Citation format unchanged

Performance:
- All heavyweight dependencies (EmbeddingService, QdrantClient,
  OllamaProvider) are backed by singletons; no re-initialization here.
- QueryExpansionService is Redis-cached; repeated queries cost 0 LLM calls.
- RetrievalProfiler replaces scattered timing code with centralized logging.
"""

import logging
from typing import Any, Optional, List, Dict, Generator, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.message import MessageRepository
from app.models.message import MessageRole
from app.services.search_service import SearchService
from app.services.prompt_builder import PromptBuilder
from app.services.query_rewriter_service import QueryRewriterService
from app.services.query_expansion_service import QueryExpansionService
from app.services.reranker_service import get_reranker
from app.services.retrieval_profiler import RetrievalProfiler
from app.services.llm import LLMFactory
from app.services.prompt_security_service import PromptSecurityService

logger = logging.getLogger(__name__)


class RAGService:
    """
    Enterprise Retrieval-Augmented Generation Service.

    Responsibilities:
    - Orchestrate the full retrieval pipeline
    - Retrieve relevant document chunks via hybrid search
    - Build grounded prompts
    - Generate answers using the configured LLM

    Sprint 11:
    - ask_with_history() — conversational non-streaming RAG
    - stream_ask_with_history() — conversational streaming RAG with
      DB persistence (message saved ONLY on successful completion)

    Sprint 12:
    - Hybrid retrieval (Dense + Keyword + RRF)
    - Query expansion (bilingual, Redis-cached)
    - Pluggable re-ranking
    - Centralized profiling via RetrievalProfiler

    Performance:
    - All heavyweight dependencies backed by singletons.
    - Every pipeline stage is profiled via RetrievalProfiler.
    """

    def __init__(self, db: Session):
        self.db = db
        self.search_service = SearchService(db)
        # LLMFactory.get_provider() returns the cached singleton — O(1).
        self.llm = LLMFactory.get_provider()
        self._msg_repo = MessageRepository(db)
        self._rewriter = QueryRewriterService()
        self._expander = QueryExpansionService()
        self._reranker = get_reranker()

    # ------------------------------------------------------------------
    # Internal: Query Expansion (with toggle)
    # ------------------------------------------------------------------

    def _expand_query(self, query: str) -> str:
        """Expand query if enabled; otherwise return as-is."""
        if settings.ENABLE_QUERY_EXPANSION:
            return self._expander.expand(query)
        return query

    # ------------------------------------------------------------------
    # Internal: Build sources list from SearchResult objects
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sources(results):
        """Convert SearchResult objects to the API source format."""
        return [
            {
                "score": float(r.score),
                "chunk_uuid": r.chunk_uuid,
                "parsed_document_id": r.parsed_document_id,
            }
            for r in results
        ]

    # ------------------------------------------------------------------
    # P2-2: Connection Lifecycle & Decoupled Persistence Helpers
    # ------------------------------------------------------------------

    def _release_db(self) -> None:
        """
        Commits and closes the initial DB session so no PostgreSQL connection
        remains checked out during external Ollama LLM inference or streaming.
        """
        if self.db is not None:
            try:
                self.db.commit()
            except Exception:
                try:
                    self.db.rollback()
                except Exception:
                    pass
            try:
                self.db.close()
            except Exception:
                pass

    def _persist_assistant_message(
        self,
        conversation_id: int,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        completion_tokens: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
    ) -> None:
        """
        Persists the assistant message using an isolated short-lived DB session
        only when persistence is actually required, preventing connection leaks.

        Token counts
        ------------
        completion_tokens and prompt_tokens must come from the authoritative
        OllamaProvider token contract (GenerationResult.token_usage or
        StreamingResult.token_usage).  Neither is estimated or fabricated here.
        If the provider metadata is unavailable (e.g. client disconnect before
        the terminal chunk), the values are stored as 0 with no fabrication.
        """
        from app.database.session import SessionLocal
        db = SessionLocal()
        # Guard: never store None in integer columns; 0 signals "unavailable".
        _completion = completion_tokens if completion_tokens is not None else 0
        _prompt = prompt_tokens if prompt_tokens is not None else 0
        _total = _prompt + _completion
        try:
            MessageRepository(db).create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=content,
                citations=citations,
                prompt_tokens=_prompt,
                completion_tokens=_completion,
                total_tokens=_total,
            )
        except Exception as exc:
            logger.error(f"Failed to persist assistant message for conv {conversation_id}: {exc}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Non-streaming Ask (stateless — backward compatible)
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        knowledge_base_id: int,
        organization_id: Optional[int] = None,
        user=None,
    ) -> dict:

        profiler = RetrievalProfiler()
        logger.info("Starting RAG pipeline (non-streaming, hybrid)...")

        # ── P0-3: Prompt Security Gate ───────────────────────────────────
        # MUST run before any search, embedding, or LLM call.
        if user is not None:
            sec = PromptSecurityService(self.db)
            decision = sec.process_prompt(
                prompt=question,
                user=user,
                kb_id=knowledge_base_id,
                org_id=organization_id,
            )
            if decision["decision"] in ("BLOCKED", "DENIED"):
                logger.warning(
                    "AUDIT_RAG | Action: prompt_rejected | User: %s | Decision: %s "
                    "| Reason: %s | Risk: %.2f",
                    user.id,
                    decision["decision"],
                    decision["reason"],
                    decision["risk_score"],
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Request blocked: {decision['reason']}",
                )

        # ── Step 1: Query Expansion ──────────────────────────────────────
        profiler.start("query_expansion")
        expanded = self._expand_query(question)
        profiler.stop("query_expansion")

        # ── Step 2: Hybrid Search (embedding + dense + keyword + RRF) ────
        results = self.search_service.hybrid_search(
            query=question,
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            expanded_query=expanded,
            profiler=profiler,
        )

        if not results:
            logger.warning("No relevant chunks found.")
            self._release_db()
            return {
                "answer": "I couldn't find enough information in the uploaded documents.",
                "sources": [],
            }

        # ── Step 3: Optional Re-ranking ──────────────────────────────────
        profiler.start("rerank")
        results = self._reranker.rerank(question, results)
        results = results[: settings.RERANK_MAX_RESULTS]
        profiler.stop("rerank")

        # ── Step 4: Build Prompt ─────────────────────────────────────────
        profiler.start("prompt_build")
        contexts = [r.text for r in results]
        prompt = PromptBuilder.build_prompt(
            question=question, contexts=contexts
        )
        profiler.stop("prompt_build")

        # ── P2-2: Release DB connection prior to external LLM inference ───
        # Guarantees zero PostgreSQL connections checked out during Ollama HTTP call.
        self._release_db()

        # ── Step 5: Generate Answer ──────────────────────────────────────
        profiler.start("llm")
        answer = self.llm.generate(prompt)
        profiler.stop("llm")

        # ── Step 6: Build Sources ────────────────────────────────────────
        sources = self._build_sources(results)

        # AI-8 Phase A: consume authoritative OllamaProvider token metadata.
        _usage = getattr(answer, "token_usage", None)
        completion_tokens = _usage.completion_tokens if _usage is not None else None
        profiler.set("token_count", completion_tokens if completion_tokens is not None else 0)
        profiler.log_report("non-streaming")

        logger.info("RAG pipeline completed successfully.")
        return {"answer": answer, "sources": sources}

    # ------------------------------------------------------------------
    # Streaming Ask (stateless — backward compatible)
    # ------------------------------------------------------------------

    def stream_ask(
        self,
        question: str,
        knowledge_base_id: int,
        organization_id: Optional[int] = None,
        user=None,
    ):
        profiler = RetrievalProfiler()
        logger.info("Starting RAG pipeline (streaming, hybrid)...")

        # ── P0-3: Prompt Security Gate ───────────────────────────────────
        # Streaming is NOT exempt from security checks.
        if user is not None:
            sec = PromptSecurityService(self.db)
            decision = sec.process_prompt(
                prompt=question,
                user=user,
                kb_id=knowledge_base_id,
                org_id=organization_id,
            )
            if decision["decision"] in ("BLOCKED", "DENIED"):
                logger.warning(
                    "AUDIT_RAG | Action: prompt_rejected (streaming) | User: %s "
                    "| Decision: %s | Reason: %s | Risk: %.2f",
                    user.id,
                    decision["decision"],
                    decision["reason"],
                    decision["risk_score"],
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Request blocked: {decision['reason']}",
                )

        # ── Step 1: Query Expansion ──────────────────────────────────────
        profiler.start("query_expansion")
        expanded = self._expand_query(question)
        profiler.stop("query_expansion")

        # ── Step 2: Hybrid Search ────────────────────────────────────────
        results = self.search_service.hybrid_search(
            query=question,
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            expanded_query=expanded,
            profiler=profiler,
        )

        if not results:
            self._release_db()
            yield "I couldn't find enough information in the uploaded documents."
            return

        # ── Step 3: Optional Re-ranking ──────────────────────────────────
        profiler.start("rerank")
        results = self._reranker.rerank(question, results)
        results = results[: settings.RERANK_MAX_RESULTS]
        profiler.stop("rerank")

        # ── Step 4: Build Prompt ─────────────────────────────────────────
        profiler.start("prompt_build")
        contexts = [r.text for r in results]
        prompt = PromptBuilder.build_prompt(
            question=question, contexts=contexts
        )
        profiler.stop("prompt_build")

        # ── P2-2: Release DB connection prior to external token streaming ─
        # Guarantees zero PostgreSQL connections checked out during Ollama streaming.
        self._release_db()

        # ── Step 5: Stream tokens ────────────────────────────────────────
        profiler.start("llm")
        first_token_recorded = False
        token_count: int = 0

        # AI-8 Phase A: hold the StreamingResult so we can read terminal token
        # metadata after the stream completes.
        streaming_result = self.llm.stream_generate(prompt)

        try:
            for token in streaming_result:
                if not first_token_recorded:
                    profiler.set_first_token()
                    first_token_recorded = True
                token_count += 1
                yield token

        finally:
            profiler.stop("llm")
            _usage_final = getattr(streaming_result, "token_usage", None)
            _obs_tokens = (
                _usage_final.completion_tokens
                if _usage_final is not None and _usage_final.completion_tokens is not None
                else token_count  # chunk count: fallback for observability only
            )
            profiler.set("token_count", _obs_tokens)
            profiler.log_report("streaming")
            logger.info("Streaming RAG pipeline completed.")

    # ------------------------------------------------------------------
    # Conversational Ask (Sprint 11 — non-streaming)
    # ------------------------------------------------------------------

    def ask_with_history(
        self,
        question: str,
        knowledge_base_id: int,
        conversation_id: int,
        user_id: int,
        organization_id: Optional[int] = None,
        user=None,
    ) -> dict:
        """
        Conversational RAG pipeline (non-streaming).
        """
        profiler = RetrievalProfiler()

        # ── P0-3: Prompt Security Gate ───────────────────────────────────
        if user is not None:
            sec = PromptSecurityService(self.db)
            decision = sec.process_prompt(
                prompt=question,
                user=user,
                kb_id=knowledge_base_id,
                org_id=organization_id,
            )
            if decision["decision"] in ("BLOCKED", "DENIED"):
                logger.warning(
                    "AUDIT_RAG | Action: prompt_rejected (conv) | User: %s "
                    "| Decision: %s | Reason: %s | Risk: %.2f",
                    user.id,
                    decision["decision"],
                    decision["reason"],
                    decision["risk_score"],
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Request blocked: {decision['reason']}",
                )

        # ── Step 1: Save user message ─────────────────────────────────────
        user_msg = self._msg_repo.create(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=question,
        )
        logger.info(f"Saved user message id={user_msg.id}")

        # ── Step 2: Retrieve history within token budget ──────────────────
        history = self._msg_repo.get_history(
            conversation_id,
            token_budget=settings.CONV_HISTORY_TOKEN_BUDGET,
        )
        # Exclude the message we just saved (it's the current question).
        history = [m for m in history if m.id != user_msg.id]

        # ── Step 3: Rewrite query ─────────────────────────────────────────
        rewritten = self._rewriter.rewrite(question, history)

        # ── Step 4: Query expansion (Sprint 12) ──────────────────────────
        profiler.start("query_expansion")
        expanded = self._expand_query(rewritten)
        profiler.stop("query_expansion")

        # ── Step 5: Hybrid search (Sprint 12) ────────────────────────────
        results = self.search_service.hybrid_search(
            query=rewritten,
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            expanded_query=expanded,
            profiler=profiler,
        )

        if not results:
            answer = "I couldn't find enough information in the uploaded documents."
            self._release_db()
            self._persist_assistant_message(
                conversation_id=conversation_id,
                content=answer,
            )
            return {"answer": answer, "sources": []}

        # ── Step 6: Optional re-ranking (Sprint 12) ──────────────────────
        profiler.start("rerank")
        results = self._reranker.rerank(rewritten, results)
        results = results[: settings.RERANK_MAX_RESULTS]
        profiler.stop("rerank")

        # ── Step 7: Build prompt ──────────────────────────────────────────
        profiler.start("prompt_build")
        contexts = [r.text for r in results]
        prompt = PromptBuilder.build_conversation_prompt(
            question=rewritten,
            contexts=contexts,
            history=history,
        )
        profiler.stop("prompt_build")

        # ── P2-2: Release DB connection prior to external LLM generation ──
        # Guarantees zero PostgreSQL connections checked out during Ollama HTTP call.
        self._release_db()

        # ── Step 8: Generate ──────────────────────────────────────────────
        profiler.start("llm")
        answer = self.llm.generate(prompt)
        profiler.stop("llm")

        # ── Step 9: Build sources ─────────────────────────────────────────
        sources = self._build_sources(results)

        # ── Step 10: Save assistant message via isolated short-lived session ─
        # AI-8 Phase A: consume authoritative OllamaProvider token metadata.
        # GenerationResult.token_usage is always present after a successful call.
        # Do NOT use len(answer.split()) — word count is not a token count.
        _usage = getattr(answer, "token_usage", None)
        completion_tokens = _usage.completion_tokens if _usage is not None else None
        prompt_tokens = _usage.prompt_tokens if _usage is not None else None
        self._persist_assistant_message(
            conversation_id=conversation_id,
            content=answer,
            citations=sources,
            completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
        )

        # Profiler: use the authoritative completion token count for observability.
        # Fall back to 0 only for display — do not fabricate a stored value.
        profiler.set("token_count", completion_tokens if completion_tokens is not None else 0)
        profiler.log_report("conversational")

        return {"answer": answer, "sources": sources}

    # ------------------------------------------------------------------
    # Conversational Streaming Ask (Sprint 11 — streaming)
    # ------------------------------------------------------------------

    def stream_ask_with_history(
        self,
        question: str,
        knowledge_base_id: int,
        conversation_id: int,
        user_id: int,
        organization_id: Optional[int] = None,
        user=None,
    ):
        """
        Conversational RAG pipeline (streaming).

        Critical guarantee
        ------------------
        The assistant message is saved to the database ONLY after the
        stream completes successfully. If streaming fails mid-way, no
        partial message is persisted.

        Pipeline
        --------
        0. Prompt Security Gate (P0-3) — blocks injection/denied access
        1. Save user message
        2. Retrieve history within token budget
        3. Rewrite follow-up question
        4. Query expansion (Sprint 12)
        5. Hybrid search (Sprint 12)
        6. Optional re-ranking (Sprint 12)
        7. Build prompt with history + context
        8. Stream tokens to caller
        9. [On success] Save assistant message + update last_message_at
        """
        profiler = RetrievalProfiler()

        # ── P0-3: Prompt Security Gate ───────────────────────────────────
        # Must run before saving the user message or any pipeline stage.
        if user is not None:
            sec = PromptSecurityService(self.db)
            decision = sec.process_prompt(
                prompt=question,
                user=user,
                kb_id=knowledge_base_id,
                org_id=organization_id,
            )
            if decision["decision"] in ("BLOCKED", "DENIED"):
                logger.warning(
                    "AUDIT_RAG | Action: prompt_rejected (conv-streaming) | User: %s "
                    "| Decision: %s | Reason: %s | Risk: %.2f",
                    user.id,
                    decision["decision"],
                    decision["reason"],
                    decision["risk_score"],
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Request blocked: {decision['reason']}",
                )

        # ── Step 1: Save user message ─────────────────────────────────────
        user_msg = self._msg_repo.create(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=question,
        )
        logger.info(f"Saved user message id={user_msg.id} (streaming)")

        # ── Step 2: History retrieval ─────────────────────────────────────
        history = self._msg_repo.get_history(
            conversation_id,
            token_budget=settings.CONV_HISTORY_TOKEN_BUDGET,
        )
        history = [m for m in history if m.id != user_msg.id]

        # ── Step 3: Query rewriting ───────────────────────────────────────
        rewritten = self._rewriter.rewrite(question, history)

        # ── Step 4: Query expansion (Sprint 12) ──────────────────────────
        profiler.start("query_expansion")
        expanded = self._expand_query(rewritten)
        profiler.stop("query_expansion")

        # ── Step 5: Hybrid search (Sprint 12) ────────────────────────────
        results = self.search_service.hybrid_search(
            query=rewritten,
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            expanded_query=expanded,
            profiler=profiler,
        )

        if not results:
            no_info = "I couldn't find enough information in the uploaded documents."
            self._release_db()
            self._persist_assistant_message(
                conversation_id=conversation_id,
                content=no_info,
            )
            yield no_info
            return

        # ── Step 6: Optional re-ranking (Sprint 12) ──────────────────────
        profiler.start("rerank")
        results = self._reranker.rerank(rewritten, results)
        results = results[: settings.RERANK_MAX_RESULTS]
        profiler.stop("rerank")

        # ── Step 7: Build prompt ──────────────────────────────────────────
        profiler.start("prompt_build")
        contexts = [r.text for r in results]
        sources = self._build_sources(results)
        prompt = PromptBuilder.build_conversation_prompt(
            question=rewritten,
            contexts=contexts,
            history=history,
        )
        profiler.stop("prompt_build")

        # ── P2-2: Release DB connection prior to external token streaming ─
        # Guarantees zero PostgreSQL connections checked out during Ollama streaming.
        self._release_db()

        # ── Step 8: Stream — accumulate for DB save ───────────────────────
        profiler.start("llm")
        first_token_recorded: bool = False
        token_count: int = 0
        accumulated_answer: str = ""
        stream_succeeded: bool = False

        # AI-8 Phase A: hold the StreamingResult so we can read terminal token
        # metadata after the stream completes.  The usage_box is mutated by
        # OllamaProvider._generator() as the done=True terminal chunk arrives.
        streaming_result = self.llm.stream_generate(prompt)

        try:
            for token in streaming_result:
                if not first_token_recorded:
                    profiler.set_first_token()
                    first_token_recorded = True
                token_count += 1
                accumulated_answer += token
                yield token

            stream_succeeded = True

        finally:
            profiler.stop("llm")

            # ── Step 9: Save assistant message ONLY on success via isolated session ──
            if stream_succeeded and accumulated_answer:
                # AI-8 Phase A: use the authoritative StreamingResult token_usage.
                # This is set by OllamaProvider from the done=True terminal chunk.
                # Do NOT use len(accumulated_answer.split()) — word count != tokens.
                # If the terminal chunk was never received (client disconnect, timeout),
                # token_usage.is_exact=False and completion_tokens=None — preserved as 0,
                # no fabrication.
                _usage = getattr(streaming_result, "token_usage", None)
                completion_tokens = (
                    _usage.completion_tokens
                    if _usage is not None and _usage.is_exact
                    else None
                )
                prompt_tokens = (
                    _usage.prompt_tokens
                    if _usage is not None and _usage.is_exact
                    else None
                )
                self._persist_assistant_message(
                    conversation_id=conversation_id,
                    content=accumulated_answer,
                    citations=sources,
                    completion_tokens=completion_tokens,
                    prompt_tokens=prompt_tokens,
                )
                logger.info(
                    f"Saved assistant message for conversation {conversation_id} "
                    f"(completion_tokens={completion_tokens}, "
                    f"is_exact={_usage.is_exact if _usage else False})"
                )
            elif not stream_succeeded:
                logger.warning(
                    f"Stream failed or cancelled for conversation {conversation_id} — "
                    "partial output NOT saved."
                )

            # Profiler: chunk count (token_count) is a yield count, NOT a true
            # token count.  Use Ollama eval_count when available for observability.
            _usage_final = getattr(streaming_result, "token_usage", None)
            _obs_tokens = (
                _usage_final.completion_tokens
                if _usage_final is not None and _usage_final.completion_tokens is not None
                else token_count  # chunk count: approximate, for profiling only
            )
            profiler.set("token_count", _obs_tokens)
            profiler.log_report("conv-streaming")
