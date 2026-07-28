import logging
import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.message import MessageRepository
from app.models.message import MessageRole
from app.services.search_service import SearchService
from app.services.prompt_builder import PromptBuilder
from app.services.query_rewriter_service import QueryRewriterService
from app.services.llm import LLMFactory

logger = logging.getLogger(__name__)


class RAGService:
    """
    Enterprise Retrieval-Augmented Generation Service.

    Responsibilities:
    - Retrieve relevant document chunks
    - Build grounded prompts
    - Generate answers using the configured LLM

    Sprint 11 Extension:
    - ask_with_history() — conversational non-streaming RAG
    - stream_ask_with_history() — conversational streaming RAG with
      DB persistence (message saved ONLY on successful completion)

    Performance:
    - All heavyweight dependencies (EmbeddingService, QdrantClient,
      OllamaProvider) are backed by singletons; no re-initialization happens
      here.
    - Every pipeline stage is timed with perf_counter and a structured
      performance report is emitted to the log after each request.
    """

    def __init__(self, db: Session):
        self.db = db
        self.search_service = SearchService(db)
        # LLMFactory.get_provider() returns the cached singleton — O(1).
        self.llm = LLMFactory.get_provider()
        self._msg_repo = MessageRepository(db)
        self._rewriter = QueryRewriterService()

    # ------------------------------------------------------------------
    # Non-streaming Ask (stateless — backward compatible)
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        knowledge_base_id: int,
    ) -> dict:

        t_total_start = time.perf_counter()
        logger.info("Starting RAG pipeline (non-streaming)...")

        # ── Step 1: Semantic Search (embedding + Qdrant retrieval) ──────
        t_embed_start = time.perf_counter()
        results = self.search_service.semantic_search(
            query=question,
            knowledge_base_id=knowledge_base_id,
        )
        t_retrieval_end = time.perf_counter()
        embedding_ms = (t_retrieval_end - t_embed_start) * 1000  # includes embed + qdrant

        if not results:
            logger.warning("No relevant chunks found.")
            return {
                "answer": "I couldn't find enough information in the uploaded documents.",
                "sources": [],
            }

        # ── Step 2: Extract Context ──────────────────────────────────────
        contexts = [item.payload["text"] for item in results]

        # ── Step 3: Build Prompt ─────────────────────────────────────────
        t_prompt_start = time.perf_counter()
        prompt = PromptBuilder.build_prompt(question=question, contexts=contexts)
        t_prompt_end = time.perf_counter()
        prompt_ms = (t_prompt_end - t_prompt_start) * 1000

        # ── Step 4: Generate Answer ──────────────────────────────────────
        t_llm_start = time.perf_counter()
        answer = self.llm.generate(prompt)
        t_llm_end = time.perf_counter()
        llm_ms = (t_llm_end - t_llm_start) * 1000

        # ── Step 5: Build Sources ────────────────────────────────────────
        sources = [
            {
                "score": float(item.score),
                "chunk_uuid": item.payload.get("chunk_uuid"),
                "parsed_document_id": item.payload.get("parsed_document_id"),
            }
            for item in results
        ]

        total_ms = (time.perf_counter() - t_total_start) * 1000
        token_count = len(answer.split())  # rough estimate

        logger.info(
            "\n"
            "┌─────────────────────────────────────────┐\n"
            "│         RAG Timing  (non-streaming)     │\n"
            "├─────────────────────────────────────────┤\n"
            f"│  Embedding + Retrieval : {embedding_ms:>8.1f} ms    │\n"
            f"│  Prompt Build          : {prompt_ms:>8.1f} ms    │\n"
            f"│  LLM Request           : {llm_ms:>8.1f} ms    │\n"
            f"│  Total                 : {total_ms:>8.1f} ms    │\n"
            f"│  ~Tokens (words)       : {token_count:>8d}       │\n"
            f"│  ~Throughput           : {(token_count/(llm_ms/1000)) if llm_ms > 0 else 0:>8.1f} tok/s │\n"
            "└─────────────────────────────────────────┘"
        )

        logger.info("RAG pipeline completed successfully.")

        return {"answer": answer, "sources": sources}

    # ------------------------------------------------------------------
    # Streaming Ask (stateless — backward compatible)
    # ------------------------------------------------------------------

    def stream_ask(
        self,
        question: str,
        knowledge_base_id: int,
    ):
        t_total_start = time.perf_counter()
        logger.info("Starting RAG pipeline (streaming)...")

        # ── Step 1: Embedding + Retrieval ────────────────────────────────
        t_embed_start = time.perf_counter()
        results = self.search_service.semantic_search(
            query=question,
            knowledge_base_id=knowledge_base_id,
        )
        t_retrieval_end = time.perf_counter()
        embedding_ms = (t_retrieval_end - t_embed_start) * 1000

        if not results:
            yield "I couldn't find enough information in the uploaded documents."
            return

        # ── Step 2: Context extraction ───────────────────────────────────
        contexts = [item.payload["text"] for item in results]

        # ── Step 3: Prompt Build ─────────────────────────────────────────
        t_prompt_start = time.perf_counter()
        prompt = PromptBuilder.build_prompt(question=question, contexts=contexts)
        t_prompt_end = time.perf_counter()
        prompt_ms = (t_prompt_end - t_prompt_start) * 1000

        # ── Step 4: Stream tokens, measuring first-token latency ─────────
        t_llm_request = time.perf_counter()
        llm_request_ms = (t_llm_request - t_prompt_end) * 1000

        first_token_ms: float | None = None
        token_count: int = 0

        try:
            for token in self.llm.stream_generate(prompt):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t_llm_request) * 1000
                token_count += 1
                # Yield immediately — do not buffer.
                yield token

        finally:
            t_done = time.perf_counter()
            total_ms = (t_done - t_total_start) * 1000
            generation_ms = (t_done - t_llm_request) * 1000
            throughput = (token_count / (generation_ms / 1000)) if generation_ms > 0 else 0

            logger.info(
                "\n"
                "┌─────────────────────────────────────────┐\n"
                "│         RAG Timing  (streaming)         │\n"
                "├─────────────────────────────────────────┤\n"
                f"│  Embedding + Retrieval : {embedding_ms:>8.1f} ms    │\n"
                f"│  Prompt Build          : {prompt_ms:>8.1f} ms    │\n"
                f"│  LLM Request overhead  : {llm_request_ms:>8.1f} ms    │\n"
                f"│  First Token           : {(first_token_ms or 0):>8.1f} ms    │\n"
                f"│  Generation (total)    : {generation_ms:>8.1f} ms    │\n"
                f"│  Total                 : {total_ms:>8.1f} ms    │\n"
                f"│  Tokens streamed       : {token_count:>8d}       │\n"
                f"│  Throughput            : {throughput:>8.1f} tok/s │\n"
                "└─────────────────────────────────────────┘"
            )
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
    ) -> dict:
        """
        Conversational RAG pipeline (non-streaming).

        Pipeline
        --------
        1. Save user message
        2. Retrieve history within token budget
        3. Rewrite follow-up question (QueryRewriterService)
        4. Semantic search with rewritten question
        5. Build prompt with history + context
        6. Generate answer
        7. Save assistant message
        8. Return response with sources
        """
        t_total_start = time.perf_counter()

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

        # ── Step 4: Semantic search ───────────────────────────────────────
        t_embed_start = time.perf_counter()
        results = self.search_service.semantic_search(
            query=rewritten,
            knowledge_base_id=knowledge_base_id,
        )
        embedding_ms = (time.perf_counter() - t_embed_start) * 1000

        if not results:
            answer = "I couldn't find enough information in the uploaded documents."
            self._msg_repo.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=answer,
            )
            return {"answer": answer, "sources": []}

        # ── Step 5: Build prompt ──────────────────────────────────────────
        contexts = [item.payload["text"] for item in results]
        prompt = PromptBuilder.build_conversation_prompt(
            question=rewritten,
            contexts=contexts,
            history=history,
        )

        # ── Step 6: Generate ──────────────────────────────────────────────
        t_llm_start = time.perf_counter()
        answer = self.llm.generate(prompt)
        llm_ms = (time.perf_counter() - t_llm_start) * 1000

        # ── Step 7: Build sources ─────────────────────────────────────────
        sources = [
            {
                "score": float(item.score),
                "chunk_uuid": item.payload.get("chunk_uuid"),
                "parsed_document_id": item.payload.get("parsed_document_id"),
            }
            for item in results
        ]

        # ── Step 8: Save assistant message ───────────────────────────────
        completion_tokens = len(answer.split())
        self._msg_repo.create(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            citations=sources,
            completion_tokens=completion_tokens,
            total_tokens=completion_tokens,
        )

        total_ms = (time.perf_counter() - t_total_start) * 1000
        logger.info(
            f"Conversational RAG (non-streaming): "
            f"embed={embedding_ms:.0f}ms llm={llm_ms:.0f}ms total={total_ms:.0f}ms"
        )

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
        4. Semantic search
        5. Build prompt with history + context
        6. Stream tokens to caller
        7. [On success] Save assistant message + update last_message_at
        """
        t_total_start = time.perf_counter()

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

        # ── Step 4: Semantic search ───────────────────────────────────────
        t_embed_start = time.perf_counter()
        results = self.search_service.semantic_search(
            query=rewritten,
            knowledge_base_id=knowledge_base_id,
        )
        embedding_ms = (time.perf_counter() - t_embed_start) * 1000

        if not results:
            no_info = "I couldn't find enough information in the uploaded documents."
            self._msg_repo.create(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=no_info,
            )
            yield no_info
            return

        # ── Step 5: Build prompt ──────────────────────────────────────────
        contexts = [item.payload["text"] for item in results]
        sources = [
            {
                "score": float(item.score),
                "chunk_uuid": item.payload.get("chunk_uuid"),
                "parsed_document_id": item.payload.get("parsed_document_id"),
            }
            for item in results
        ]
        prompt = PromptBuilder.build_conversation_prompt(
            question=rewritten,
            contexts=contexts,
            history=history,
        )

        # ── Step 6: Stream — accumulate for DB save ───────────────────────
        t_llm_request = time.perf_counter()
        first_token_ms: float | None = None
        token_count: int = 0
        accumulated_answer: str = ""
        stream_succeeded: bool = False

        try:
            for token in self.llm.stream_generate(prompt):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t_llm_request) * 1000
                token_count += 1
                accumulated_answer += token
                yield token

            stream_succeeded = True

        finally:
            t_done = time.perf_counter()
            total_ms = (t_done - t_total_start) * 1000
            generation_ms = (t_done - t_llm_request) * 1000
            throughput = (token_count / (generation_ms / 1000)) if generation_ms > 0 else 0

            # ── Step 7: Save assistant message ONLY on success ───────────
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

            logger.info(
                "\n"
                "┌─────────────────────────────────────────┐\n"
                "│    Conversational RAG Timing (stream)   │\n"
                "├─────────────────────────────────────────┤\n"
                f"│  Embedding + Retrieval : {embedding_ms:>8.1f} ms    │\n"
                f"│  First Token           : {(first_token_ms or 0):>8.1f} ms    │\n"
                f"│  Generation (total)    : {generation_ms:>8.1f} ms    │\n"
                f"│  Total                 : {total_ms:>8.1f} ms    │\n"
                f"│  Tokens streamed       : {token_count:>8d}       │\n"
                f"│  Throughput            : {throughput:>8.1f} tok/s │\n"
                "└─────────────────────────────────────────┘"
            )

