"""
QueryRewriterService — Follow-up Question Resolution.

Single Responsibility: rewrite ambiguous follow-up questions into
self-contained queries using conversation history.

Architecture
------------
- Uses OllamaProvider singleton (no new connections created).
- Falls back to the original question on ANY failure — never blocks a chat.
- No database access — pure LLM transformation layer.
- Stateless: called per-request with injected history.

Examples
--------
History:  "What is Generative Engine Optimization?"
Followup: "Explain more."
Output:   "Explain Generative Engine Optimization in more detail."

History:  "What is GEO?"
Followup: "Compare it with SEO."
Output:   "Compare Generative Engine Optimization with Search Engine Optimization."
"""

import logging
from typing import List

from app.models.message import Message
from app.services.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

# System prompt for the rewriter — kept minimal to run fast on CPU.
_REWRITER_SYSTEM = (
    "You are a query rewriting assistant. "
    "Given a conversation history and a follow-up question, "
    "rewrite the follow-up question into a complete, standalone question "
    "that can be understood without the conversation history. "
    "Preserve the original language (Arabic or English). "
    "If the follow-up is already standalone, return it unchanged. "
    "Return ONLY the rewritten question — no explanation, no prefix, no quotes."
)

# Maximum tokens for the rewriter output — we only need one sentence.
_REWRITER_MAX_TOKENS = 80

# Maximum history turns to include in the rewriter context (saves tokens).
_MAX_HISTORY_TURNS = 6


class QueryRewriterService:
    """
    Rewrites follow-up questions into standalone queries.

    Uses Qwen3:8b via the existing OllamaProvider singleton.
    Never opens a new HTTP connection — reuses the persistent session.
    """

    def __init__(self) -> None:
        # Reuse the singleton — zero re-initialization cost.
        self._llm = OllamaProvider.get_instance()

    def rewrite(
        self,
        question: str,
        history: List[Message],
    ) -> str:
        """
        Rewrite the question if the conversation has history.

        Parameters
        ----------
        question : str
            The current user question (possibly a follow-up).
        history : list[Message]
            Previous messages, oldest-first, within the token budget.

        Returns
        -------
        str
            The rewritten standalone question, or the original question
            if rewriting is unnecessary or fails.
        """
        # No history → nothing to resolve → return as-is.
        if not history:
            return question

        # Check if the question looks like a follow-up (short, pronoun-heavy,
        # or contains referential terms). If not, skip the LLM call entirely.
        if not self._needs_rewrite(question):
            return question

        try:
            prompt = self._build_prompt(question, history)
            rewritten = self._llm.generate(
                prompt,
                temperature=0.0,          # Deterministic rewriting.
                max_tokens=_REWRITER_MAX_TOKENS,
            ).strip()

            if rewritten and len(rewritten) > 2:
                logger.debug(
                    f"QueryRewriter: '{question}' → '{rewritten}'"
                )
                return rewritten

        except Exception as exc:
            # Graceful degradation — never block the user's request.
            logger.warning(
                f"QueryRewriter failed (using original question): {exc}"
            )

        return question

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _needs_rewrite(self, question: str) -> bool:
        """
        Heuristic: determine if the question likely contains unresolved
        references that require conversation context to understand.

        Triggers rewrite if the question:
        - Is short (≤ 6 words) — likely a follow-up fragment
        - Contains common referential terms in English or Arabic
        """
        words = question.strip().split()
        if not words:
            return False
        referential_triggers = {
            # English
            "it", "this", "that", "they", "them", "its", "their",
            "more", "further", "elaborate", "explain", "compare",
            "difference", "vs", "versus", "also", "additionally",
            # Arabic
            "هذا", "هذه", "ذلك", "تلك", "هم", "هي", "هو",
            "أكثر", "المزيد", "اشرح", "قارن", "الفرق",
        }
        lower_words = {w.lower().strip("?.,!") for w in words}
        return bool(lower_words & referential_triggers)

    def _build_prompt(self, question: str, history: List[Message]) -> str:
        """Build the rewriter prompt with truncated history."""
        # Take only the last N turns to keep the prompt short.
        recent = history[-_MAX_HISTORY_TURNS:]

        history_lines = []
        for msg in recent:
            prefix = "User" if msg.role == "user" else "Assistant"
            # Truncate long messages for the rewriter context.
            snippet = msg.content[:300].replace("\n", " ")
            history_lines.append(f"{prefix}: {snippet}")

        history_block = "\n".join(history_lines)

        return (
            f"{_REWRITER_SYSTEM}\n\n"
            f"=== CONVERSATION HISTORY ===\n"
            f"{history_block}\n\n"
            f"=== FOLLOW-UP QUESTION ===\n"
            f"{question}\n\n"
            f"=== REWRITTEN STANDALONE QUESTION ===\n"
        )
