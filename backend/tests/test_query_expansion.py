"""
AI-4 Phase 1 — QueryExpansionService Cache Wiring Tests.

Tests the seven behavioral requirements identified in the AI-4 Phase 1
cache contract audit. No live Redis or Ollama is required — all external
dependencies are mocked using the same conventions as test_rag.py and
test_embedding.py.

Coverage
--------
1. test_expand_cache_hit_skips_llm
2. test_expand_cache_miss_calls_llm_and_writes_cache
3. test_expand_cache_key_normalization
4. test_expand_redis_unavailable_falls_back_to_llm
5. test_expand_redis_get_error_falls_back_to_llm
6. test_expand_glossary_bypasses_cache_and_llm
7. test_expand_repeated_query_llm_called_once
"""

import pytest
from unittest.mock import MagicMock, patch

import app.services.query_expansion_service as qes


@pytest.fixture(autouse=True)
def reset_shared_redis():
    """Reset shared Redis singleton between tests for clean isolation."""
    qes._shared_redis = None
    qes._redis_init_attempted = False
    yield
    qes._shared_redis = None
    qes._redis_init_attempted = False


# ---------------------------------------------------------------------------
# Test 1 — Cache HIT: cached value returned, LLM never called
# ---------------------------------------------------------------------------

def test_expand_cache_hit_skips_llm():
    """
    Given a cached expansion in Redis, expand() must:
    - Return the cached value directly.
    - NOT call OllamaProvider.generate().
    """
    cached_value = "Saudi AI Artificial Intelligence KSA"

    with patch("app.services.query_expansion_service.OllamaProvider") as mock_ollama_cls, \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_llm = MagicMock()
        mock_ollama_cls.get_instance.return_value = mock_llm

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.get.return_value = cached_value  # cache HIT
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()
        svc._llm = mock_llm
        svc._redis = mock_redis_instance

        result = svc.expand("Saudi AI")

    assert result == cached_value, f"Expected cached value, got: {result!r}"
    mock_llm.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2 — Cache MISS: LLM called, result written to cache
# ---------------------------------------------------------------------------

def test_expand_cache_miss_calls_llm_and_writes_cache():
    """
    Given a cache miss (Redis returns None), expand() must:
    - Call OllamaProvider.generate() once.
    - Write the LLM result to the cache via redis.setex.
    - Return the LLM-generated expansion.
    """
    llm_expansion = "Vision 2030 Saudi Arabia KSA Strategy"

    with patch("app.services.query_expansion_service.OllamaProvider") as mock_ollama_cls, \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_llm = MagicMock()
        mock_llm.generate.return_value = llm_expansion
        mock_ollama_cls.get_instance.return_value = mock_llm

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.get.return_value = None  # cache MISS
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()
        svc._llm = mock_llm
        svc._redis = mock_redis_instance

        result = svc.expand("Vision 2030")

    assert result == llm_expansion
    mock_llm.generate.assert_called_once()
    # Verify cache write happened: setex must have been called once
    mock_redis_instance.setex.assert_called_once()
    # The value written must be the LLM expansion
    written_value = mock_redis_instance.setex.call_args[0][2]
    assert written_value == llm_expansion


# ---------------------------------------------------------------------------
# Test 3 — Cache key normalization
# ---------------------------------------------------------------------------

def test_expand_cache_key_normalization():
    """
    _cache_key() must produce the same key for queries that are
    identical after strip() + lower().

    "  Saudi AI  ", "Saudi AI", and "saudi ai" must all produce the same key.
    "SDAIA" and "sdaia" must produce the same key.
    """
    with patch("app.services.query_expansion_service.OllamaProvider"), \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()

    key_padded = svc._cache_key("  Saudi AI  ")
    key_clean  = svc._cache_key("Saudi AI")
    key_lower  = svc._cache_key("saudi ai")
    key_upper  = svc._cache_key("SDAIA")
    key_lower2 = svc._cache_key("sdaia")

    assert key_padded == key_clean, "Padding whitespace must not affect key"
    assert key_clean  == key_lower, "Case must not affect key"
    assert key_upper  == key_lower2, "Uppercase must normalize to lowercase"

    # Keys must have the expected namespace prefix
    assert key_clean.startswith("arabiq:qexp:"), f"Unexpected key prefix: {key_clean!r}"

    # Key length: prefix "arabiq:qexp:" (12) + 16 hex chars = 28 total
    assert len(key_clean) == 28, f"Unexpected key length: {len(key_clean)}"


# ---------------------------------------------------------------------------
# Test 4 — Redis unavailable at construction: LLM fallback works
# ---------------------------------------------------------------------------

def test_expand_redis_unavailable_falls_back_to_llm():
    """
    When Redis is unavailable at construction time, self._redis is None.
    expand() must still call the LLM and return the expansion.
    """
    llm_expansion = "AI Artificial Intelligence Machine Learning"

    with patch("app.services.query_expansion_service.OllamaProvider") as mock_ollama_cls, \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_llm = MagicMock()
        mock_llm.generate.return_value = llm_expansion
        mock_ollama_cls.get_instance.return_value = mock_llm

        # Simulate Redis unavailable: ping raises, __init__ sets _redis = None
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.side_effect = ConnectionError("Redis down")
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()
        svc._llm = mock_llm

    # _redis must be None after construction failure
    assert svc._redis is None

    result = svc.expand("machine learning")

    assert result == llm_expansion
    mock_llm.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5 — Redis GET error at runtime: LLM fallback works
# ---------------------------------------------------------------------------

def test_expand_redis_get_error_falls_back_to_llm():
    """
    When _get_cached() raises at runtime (Redis connected but GET fails),
    expand() must fall through to the LLM path without raising.
    """
    llm_expansion = "NLP Natural Language Processing Arabic Text"

    with patch("app.services.query_expansion_service.OllamaProvider") as mock_ollama_cls, \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_llm = MagicMock()
        mock_llm.generate.return_value = llm_expansion
        mock_ollama_cls.get_instance.return_value = mock_llm

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.get.side_effect = RuntimeError("Redis GET failed")
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()
        svc._llm = mock_llm
        svc._redis = mock_redis_instance

        result = svc.expand("natural language processing")

    # Must not raise; must return LLM result
    assert result == llm_expansion
    mock_llm.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6 — Glossary match bypasses BOTH cache and LLM
# ---------------------------------------------------------------------------

def test_expand_glossary_bypasses_cache_and_llm():
    """
    For queries matching the static glossary, expand() must:
    - Return immediately with the glossary expansion.
    - NOT touch Redis (no GET, no SETEX).
    - NOT call OllamaProvider.generate().
    """
    with patch("app.services.query_expansion_service.OllamaProvider") as mock_ollama_cls, \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_llm = MagicMock()
        mock_ollama_cls.get_instance.return_value = mock_llm

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()
        svc._llm = mock_llm
        svc._redis = mock_redis_instance

        # "annual leave" is in the static glossary
        result = svc.expand("annual leave policy")

    assert "الإجازة السنوية" in result, f"Expected Arabic glossary expansion in: {result!r}"
    assert "annual leave policy" in result, f"Original query must be preserved: {result!r}"
    mock_redis_instance.get.assert_not_called()
    mock_redis_instance.setex.assert_not_called()
    mock_llm.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7 — Repeated identical query: LLM called exactly once
# ---------------------------------------------------------------------------

def test_expand_repeated_query_llm_called_once():
    """
    Two calls to expand() with the same query must result in:
    - First call:  cache miss → LLM called → result cached.
    - Second call: cache hit  → LLM NOT called → cached value returned.

    Net: OllamaProvider.generate() called exactly once across two invocations.
    """
    llm_expansion = "Regulation Personal Data Privacy KSA"
    query = "data privacy"  # NOT in static glossary

    llm_call_count = [0]
    cache_store: dict = {}

    def fake_get(key):
        return cache_store.get(key)

    def fake_setex(key, ttl, value):
        cache_store[key] = value

    def fake_generate(prompt, **kwargs):
        llm_call_count[0] += 1
        return llm_expansion

    with patch("app.services.query_expansion_service.OllamaProvider") as mock_ollama_cls, \
         patch("app.services.query_expansion_service.redis") as mock_redis_mod:

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = fake_generate
        mock_ollama_cls.get_instance.return_value = mock_llm

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.get.side_effect = fake_get
        mock_redis_instance.setex.side_effect = fake_setex
        mock_redis_mod.Redis.from_url.return_value = mock_redis_instance

        from app.services.query_expansion_service import QueryExpansionService
        svc = QueryExpansionService()
        svc._llm = mock_llm
        svc._redis = mock_redis_instance

        result1 = svc.expand(query)
        result2 = svc.expand(query)

    assert result1 == llm_expansion, f"First call should return LLM result: {result1!r}"
    assert result2 == llm_expansion, f"Second call should return cached result: {result2!r}"
    assert llm_call_count[0] == 1, (
        f"OllamaProvider.generate() must be called exactly once, "
        f"but was called {llm_call_count[0]} time(s)"
    )
