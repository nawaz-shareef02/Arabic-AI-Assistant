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
from typing import Optional, List, Dict, Generator, Tuple

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
    # Non-streaming Ask (stateless — backward compatible)
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        knowledge_base_id: int,
        organization_id: Optional[int] = None,
    ) -> dict:

        profiler = RetrievalProfiler()
        logger.info("Starting RAG pipeline (non-streaming, hybrid)...")

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

        # ── Step 5: Generate Answer ──────────────────────────────────────
        profiler.start("llm")
        answer = self.llm.generate(prompt)
        profiler.stop("llm")

        # ── Step 6: Build Sources ────────────────────────────────────────
        sources = self._build_sources(results)

        profiler.set("token_count", len(answer.split()))
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
    ):
        profiler = RetrievalProfiler()
        logger.info("Starting RAG pipeline (streaming, hybrid)...")

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

        # ── Step 5: Stream tokens ────────────────────────────────────────
        profiler.start("llm")
        first_token_recorded = False
        token_count: int = 0

        try:
            for token in self.llm.stream_generate(prompt):
                if not first_token_recorded:
                    profiler.set_first_token()
                    first_token_recorded = True
                token_count += 1
                yield token

        finally:
            profiler.stop("llm")
            profiler.set("token_count", token_count)
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
    ) -> dict:
        """
        Conversational RAG pipeline (non-streaming).
        """
        profiler = RetrievalProfiler()

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
            self._msg_repo.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
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

        # ── Step 8: Generate ──────────────────────────────────────────────
        profiler.start("llm")
        answer = self.llm.generate(prompt)
        profiler.stop("llm")

        # ── Step 9: Build sources ─────────────────────────────────────────
        sources = self._build_sources(results)

        # ── Step 10: Save assistant message ───────────────────────────────
        completion_tokens = len(answer.split())
        self._msg_repo.create(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            citations=sources,
            completion_tokens=completion_tokens,
            total_tokens=completion_tokens,
        )

        profiler.set("token_count", completion_tokens)
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
            expanded_query=expanded,
            profiler=profiler,
        )

        if not results:
            no_info = "I couldn't find enough information in the uploaded documents."
            self._msg_repo.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
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

        # ── Step 8: Stream — accumulate for DB save ───────────────────────
        profiler.start("llm")
        first_token_recorded: bool = False
        token_count: int = 0
        accumulated_answer: str = ""
        stream_succeeded: bool = False

        try:
            for token in self.llm.stream_generate(prompt):
                if not first_token_recorded:
                    profiler.set_first_token()
                    first_token_recorded = True
                token_count += 1
                accumulated_answer += token
                yield token

            stream_succeeded = True

        finally:
            profiler.stop("llm")

            # ── Step 9: Save assistant message ONLY on success ───────────
            if stream_succeeded and accumulated_answer:
                completion_tokens = len(accumulated_answer.split())
                self._msg_repo.create(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=accumulated_answer,
                    citations=sources,
                    completion_tokens=completion_tokens,
                    total_tokens=completion_tokens,
                )
                logger.info(
                    f"Saved assistant message for conversation {conversation_id}"
                )
            elif not stream_succeeded:
                logger.warning(
                    f"Stream failed for conversation {conversation_id} — "
                    "partial output NOT saved."
                )

            profiler.set("token_count", token_count)
            profiler.log_report("conv-streaming")
