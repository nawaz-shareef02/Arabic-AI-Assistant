"""
TitleService — Automatic Conversation Title Generation.

Single Responsibility: generate a ≤5-word title for a new conversation
from the user's first message using Qwen3:8b.

Architecture
------------
- Uses OllamaProvider singleton (no new connections).
- Called ONCE per conversation when title is None.
- Never regenerates an existing title.
- Falls back to a truncated question on ANY LLM failure.
- Never blocks the streaming response — title generation is fire-and-forget
  (called after the message has been saved and the stream has completed).
"""

import logging
import re

from app.services.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

_TITLE_SYSTEM = (
    "Generate a concise conversation title of at most 5 words based on the "
    "following question. The title must be in the same language as the question "
    "(Arabic or English). Return ONLY the title — no punctuation at the end, "
    "no quotes, no explanation."
)

_TITLE_MAX_TOKENS = 20       # 5 words @ ~4 tokens/word
_TITLE_TEMPERATURE = 0.2     # Slight creativity for varied titles


class TitleService:
    """
    Generates a short conversation title using Qwen3:8b.

    Idempotency contract
    --------------------
    This service only GENERATES the title string.
    ConversationService.set_title_if_empty() enforces the "only once" rule
    at the persistence layer.
    """

    def __init__(self) -> None:
        self._llm = OllamaProvider.get_instance()

    def generate(self, first_question: str) -> str:
        """
        Generate a ≤5-word title for the given question.

        Falls back to a truncated version of the question if the LLM fails.

        Parameters
        ----------
        first_question : str
            The user's first message in the conversation.

        Returns
        -------
        str
            A short title string (≤5 words, ≤50 chars).
        """
        try:
            prompt = (
                f"{_TITLE_SYSTEM}\n\n"
                f"Question: {first_question[:500]}\n\n"
                f"Title:"
            )
            raw = self._llm.generate(
                prompt,
                temperature=_TITLE_TEMPERATURE,
                max_tokens=_TITLE_MAX_TOKENS,
            ).strip()

            title = self._clean(raw)
            if title:
                logger.debug(f"TitleService generated: '{title}'")
                return title

        except Exception as exc:
            logger.warning(f"TitleService failed, using fallback: {exc}")

        # Fallback: first 5 words of the question.
        return self._fallback(first_question)

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _clean(self, raw: str) -> str:
        """
        Sanitize the LLM output:
        - Strip wrapping quotes, leading/trailing whitespace.
        - Truncate to 5 words.
        - Truncate to 50 characters.
        """
        # Remove surrounding quotes the model sometimes adds.
        cleaned = raw.strip().strip('"\'')
        # Collapse newlines into spaces.
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Take first 5 words only.
        words = cleaned.split()[:5]
        title = " ".join(words)
        return title[:50]

    def _fallback(self, question: str) -> str:
        """Truncate the question to 5 words as a safe fallback title."""
        words = question.strip().split()[:5]
        title = " ".join(words)
        return title[:50] or "New Conversation"
