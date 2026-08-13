"""
QueryExpansionService — Bilingual Query Expansion with Redis Cache.

Single Responsibility: expand the internal retrieval query with synonyms,
abbreviations, language variants, and plural forms to improve keyword
search recall. The user-visible query is NEVER modified.

Architecture
------------
- Uses OllamaProvider singleton (no new connections created).
- Redis-cached: identical queries return cached expansions instantly,
  eliminating redundant LLM calls.
- Graceful degradation: returns original query on any failure (Redis down,
  LLM error, malformed response).
- Stateless: called per-request with no stored state.

Examples
--------
Query:   "Saudi AI"
Expanded: "Saudi AI Artificial Intelligence KSA Saudi Arabia AI Strategy"

Query:   "الذكاء الاصطناعي"
Expanded: "الذكاء الاصطناعي AI Artificial Intelligence تعلم الآلة"
"""

import hashlib
import logging
from typing import Optional

import redis

from app.core.config import settings
from app.services.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

_EXPANSION_SYSTEM = (
    "You are a search query expansion assistant for an Arabic-English knowledge platform. "
    "Given a search query, generate additional search terms that would help find relevant documents.\n"
    "Include:\n"
    "- Synonyms and related terms\n"
    "- Abbreviations and their full forms (e.g., AI → Artificial Intelligence)\n"
    "- Arabic and English translations or variants of the same concept\n"
    "- Plural and singular forms\n"
    "- Related technical terms\n\n"
    "Return the original query terms followed by expanded terms as a single "
    "space-separated list. No explanations, no numbering, no punctuation, no quotes."
)

_EXPANSION_MAX_TOKENS = 60


class QueryExpansionService:
    """
    Expands search queries with synonyms, translations, and variants.

    Uses Qwen3 via the OllamaProvider singleton.
    Redis-cached to avoid redundant LLM calls for repeated queries.

    Cache key: SHA-256 of the lowercased, stripped query.
    Cache TTL: settings.QUERY_EXPANSION_CACHE_TTL (default 3600s).
    """

    def __init__(self) -> None:
        self._llm = OllamaProvider.get_instance()
        self._redis: Optional[redis.Redis] = None
        try:
            self._redis = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                protocol=2,
                socket_connect_timeout=2,
            )
            self._redis.ping()
            logger.debug("QueryExpansionService: Redis cache connected.")
        except Exception as exc:
            logger.warning(
                f"QueryExpansionService: Redis unavailable, caching disabled: {exc}"
            )
            self._redis = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def expand(self, query: str) -> str:
        """
        Expand the query with additional retrieval terms.

        Parameters
        ----------
        query : str
            The rewritten standalone query from QueryRewriterService.

        Returns
        -------
        str
            The expanded query string (original + expanded terms).
            Falls back to the original query on any failure.
        """
        if not query or len(query.strip()) < 2:
            return query

        # ── Fast Static Glossary Mapping (0ms Latency) ────────────────────
        glossary_terms = {
            "probation": "فترة التجربة 90 يوما 30 يوما",
            "probation period": "فترة التجربة 90 يوما 30 يوما",
            "notice period": "مهلة إشعار إنهاء الخدمة 60 يوما 30 يوما",
            "severance": "مكافأة نهاية الخدمة",
            "severance pay": "مكافأة نهاية الخدمة",
            "annual leave": "الإجازة السنوية 21 يوما 30 يوما",
            "sick leave": "الإجازة المرضية 30 يوما 60 يوما",
            "maternity leave": "إجازة الأمومة 10 أسابيع",
            "working hours": "ساعات العمل 8 ساعات 40 ساعة 6 ساعات رمضان",
            "sdaia": "الهيئة السعودية لتنظيم البيانات 72 ساعة اختراق البيانات",
            "pdpl": "حماية البيانات الشخصية 5 سنوات",
        }

        query_lower = query.lower()
        matched_expansions = [val for key, val in glossary_terms.items() if key in query_lower]
        if matched_expansions:
            static_expanded = f"{query} {' '.join(matched_expansions)}"
            logger.debug(f"QueryExpansion static HIT: '{query}' -> '{static_expanded}'")
            return static_expanded

        # ── Check Redis cache ──────────────────────────────────────────

        # ── Generate expansion via LLM ───────────────────────────────────
        try:
            prompt = (
                f"{_EXPANSION_SYSTEM}\n\n"
                f"Query: {query}\n\n"
                f"Expanded terms:"
            )
            expanded = self._llm.generate(
                prompt,
                temperature=0.0,
                max_tokens=_EXPANSION_MAX_TOKENS,
            ).strip()

            if expanded and len(expanded) > 2:
                self._set_cached(cache_key, expanded)
                logger.debug(f"QueryExpansion: '{query}' → '{expanded}'")
                return expanded

        except Exception as exc:
            logger.warning(f"QueryExpansion failed (using original): {exc}")

        return query

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, query: str) -> str:
        """Deterministic cache key from the normalized query."""
        normalized = query.strip().lower()
        hash_val = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"arabiq:qexp:{hash_val}"

    def _get_cached(self, key: str) -> Optional[str]:
        """Read from Redis; return None on miss or error."""
        if self._redis is None:
            return None
        try:
            return self._redis.get(key)
        except Exception:
            return None

    def _set_cached(self, key: str, value: str) -> None:
        """Write to Redis with TTL; silently ignore failures."""
        if self._redis is None:
            return
        try:
            self._redis.setex(key, settings.QUERY_EXPANSION_CACHE_TTL, value)
        except Exception as exc:
            logger.warning(f"QueryExpansion cache SET failed: {exc}")
