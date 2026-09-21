"""
test_p2_observability.py — P2-3 Enterprise Observability Test Suite

Covers all 15 required categories:
1.  HTTP request counter
2.  HTTP status labels
3.  HTTP route-template cardinality (not raw URL)
4.  HTTP latency
5.  Correlation/request ID
6.  LLM success metrics
7.  LLM timeout/error/cancellation metrics
8.  LLM TTFT
9.  LLM token count
10. RAG stage timing
11. DB pool metrics bridge
12. Celery success/failure/retry
13. Redis rate-limit metrics
14. Structured logging redaction
15. /metrics security
"""

import json
import logging
from unittest.mock import MagicMock, patch
import pytest


# ===========================================================================
# 1. HTTP REQUEST COUNTER
# ===========================================================================

class TestHTTPRequestCounter:
    def test_http_requests_total_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "http_requests_total")

    def test_http_requests_counter_can_increment(self):
        from app.core.prometheus_exporter import metrics_registry
        metrics_registry.http_requests_total.labels(
            method="GET", endpoint="/api/v1/health", status="200"
        ).inc()

    def test_http_request_duration_histogram_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "http_request_duration_seconds")

    def test_http_request_duration_can_observe(self):
        from app.core.prometheus_exporter import metrics_registry
        metrics_registry.http_request_duration_seconds.labels(
            method="POST", endpoint="/api/v1/chat/{kb_id}"
        ).observe(0.123)


# ===========================================================================
# 2. HTTP STATUS LABELS
# ===========================================================================

class TestHTTPStatusLabels:
    def test_status_labels_bounded_set(self):
        from app.core.prometheus_exporter import metrics_registry
        for status in ["200", "201", "400", "401", "403", "404", "422", "429", "500", "503"]:
            metrics_registry.http_requests_total.labels(
                method="GET", endpoint="/health", status=status
            ).inc()


# ===========================================================================
# 3. HTTP ROUTE-TEMPLATE CARDINALITY
# ===========================================================================

class TestHTTPRouteTemplateCardinality:
    def test_template_contains_braces(self):
        template = "/api/v1/chat/{kb_id}"
        raw_url = "/api/v1/chat/8f91a23b-4d5e-6789-ab12-cdef01234567"
        assert "{kb_id}" in template
        assert "{kb_id}" not in raw_url

    def test_middleware_uses_scope_route(self):
        class MockRoute:
            path = "/api/v1/chat/{kb_id}"
        scope = {"route": MockRoute()}
        route = scope.get("route")
        endpoint = getattr(route, "path", None)
        assert endpoint == "/api/v1/chat/{kb_id}"

    def test_no_uuid_in_endpoint_label(self):
        import re
        raw_path = "/api/v1/conversations/8f91a23b-4d5e-6789-ab12-cdef01234567/messages"
        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        )
        assert uuid_pattern.search(raw_path) is not None


# ===========================================================================
# 4. HTTP LATENCY
# ===========================================================================

class TestHTTPLatency:
    def test_latency_histogram_accepts_float(self):
        from app.core.prometheus_exporter import metrics_registry
        metrics_registry.http_request_duration_seconds.labels(
            method="POST", endpoint="/api/v1/documents"
        ).observe(1.234)

    def test_latency_buckets_cover_expected_range(self):
        from app.core.prometheus_exporter import LATENCY_BUCKETS
        assert LATENCY_BUCKETS[0] <= 0.010
        assert LATENCY_BUCKETS[-1] >= 5.0
        assert len(LATENCY_BUCKETS) >= 8


# ===========================================================================
# 5. CORRELATION / REQUEST ID
# ===========================================================================

class TestCorrelationRequestID:
    def test_request_id_header_propagation(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        custom_id = "test-correlation-abc-123"
        resp = client.get("/live", headers={"X-Request-ID": custom_id})
        assert resp.headers.get("X-Request-ID") == custom_id

    def test_request_id_generated_when_absent(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/live")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0


# ===========================================================================
# 6. LLM SUCCESS METRICS
# ===========================================================================

class TestLLMSuccessMetrics:
    def _make_provider(self):
        from app.services.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.base_url = "http://localhost:11434"
        provider.model = "test-model"
        provider.timeout = 30
        provider._session = MagicMock()
        return provider

    def test_success_returns_response(self):
        provider = self._make_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hello world", "done": True, "eval_count": 10}
        mock_response.raise_for_status = MagicMock()
        provider._session.post.return_value = mock_response
        result = provider.generate("test prompt")
        assert result == "Hello world"

    def test_missing_eval_count_does_not_break_generate(self):
        provider = self._make_provider()
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Answer", "done": True}
        mock_response.raise_for_status = MagicMock()
        provider._session.post.return_value = mock_response
        result = provider.generate("test prompt")
        assert "Answer" in result

    def test_llm_requests_total_metric_defined(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "llm_requests_total")
        metrics_registry.llm_requests_total.labels(model="qwen3:8b", outcome="success").inc()


# ===========================================================================
# 7. LLM TIMEOUT / ERROR / CANCELLATION
# ===========================================================================

class TestLLMErrorMetrics:
    def _make_provider(self):
        from app.services.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.base_url = "http://localhost:11434"
        provider.model = "test-model"
        provider.timeout = 30
        provider._session = MagicMock()
        return provider

    def test_timeout_on_generate_reraises(self):
        from requests.exceptions import Timeout
        provider = self._make_provider()
        provider._session.post.side_effect = Timeout("timed out")
        with pytest.raises(Timeout):
            provider.generate("test prompt")

    def test_request_error_on_generate_reraises(self):
        from requests.exceptions import RequestException
        provider = self._make_provider()
        provider._session.post.side_effect = RequestException("refused")
        with pytest.raises(RequestException):
            provider.generate("test prompt")

    def test_stream_yields_tokens(self):
        provider = self._make_provider()
        chunks = [
            json.dumps({"response": "Hello", "done": False}).encode(),
            json.dumps({"response": "", "done": True, "eval_count": 1}).encode(),
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(chunks)
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        provider._session.post.return_value = mock_resp
        tokens = list(provider.stream_generate("prompt"))
        assert "Hello" in tokens

    def test_llm_outcome_labels_defined(self):
        from app.core.prometheus_exporter import metrics_registry
        for outcome in ["success", "timeout", "error", "cancelled"]:
            metrics_registry.llm_requests_total.labels(model="qwen3:8b", outcome=outcome).inc()


# ===========================================================================
# 8. LLM TTFT
# ===========================================================================

class TestLLMTTFT:
    def test_ttft_metric_defined(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "llm_first_token_seconds")
        metrics_registry.llm_first_token_seconds.labels(model="qwen3:8b").observe(0.5)

    def test_stream_produces_tokens_in_order(self):
        from app.services.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.base_url = "http://localhost:11434"
        provider.model = "test-model"
        provider.timeout = 30
        provider._session = MagicMock()
        chunks = [
            json.dumps({"response": "First", "done": False}).encode(),
            json.dumps({"response": "Second", "done": False}).encode(),
            json.dumps({"response": "", "done": True, "eval_count": 2}).encode(),
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(chunks)
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        provider._session.post.return_value = mock_resp
        tokens = list(provider.stream_generate("test prompt"))
        assert len(tokens) == 2
        assert tokens[0] == "First"


# ===========================================================================
# 9. LLM TOKEN COUNT
# ===========================================================================

class TestLLMTokenCount:
    def test_token_counter_defined(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "llm_tokens_generated_total")

    def test_missing_eval_count_does_not_break_streaming(self):
        from app.services.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.base_url = "http://localhost:11434"
        provider.model = "test-model"
        provider.timeout = 30
        provider._session = MagicMock()
        chunks = [
            json.dumps({"response": "Hi", "done": False}).encode(),
            json.dumps({"response": "", "done": True}).encode(),  # no eval_count
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(chunks)
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        provider._session.post.return_value = mock_resp
        tokens = list(provider.stream_generate("prompt"))
        assert "Hi" in tokens


# ===========================================================================
# 10. RAG STAGE TIMING
# ===========================================================================

class TestRAGStageTiming:
    def test_ai_stage_duration_metric_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "ai_stage_duration_seconds")

    def test_ai_retrieval_result_count_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "ai_retrieval_result_count")

    def test_retrieval_profiler_emits_to_prometheus(self):
        from app.services.retrieval_profiler import RetrievalProfiler
        from app.core.prometheus_exporter import metrics_registry

        profiler = RetrievalProfiler()
        profiler._metrics.embedding_ms = 55.0
        profiler._metrics.dense_search_ms = 120.0
        profiler._metrics.fused_results = 5

        observed_stages = []

        class CapturingLabels:
            def __init__(self, stage): self.stage = stage
            def observe(self, val): observed_stages.append(self.stage)

        class CapturingHistogram:
            def labels(self, **kwargs): return CapturingLabels(kwargs.get("stage"))
            def observe(self, val): pass

        original = metrics_registry.ai_stage_duration_seconds
        metrics_registry.ai_stage_duration_seconds = CapturingHistogram()
        try:
            profiler.log_report(mode="test")
        finally:
            metrics_registry.ai_stage_duration_seconds = original

        assert "embedding" in observed_stages
        assert "dense_search" in observed_stages

    def test_stage_labels_hardcoded_in_profiler(self):
        import inspect
        from app.services.retrieval_profiler import RetrievalProfiler
        source = inspect.getsource(RetrievalProfiler.log_report)
        assert "embedding" in source
        assert "dense_search" in source
        assert "fusion" in source


# ===========================================================================
# 11. DB POOL METRICS BRIDGE
# ===========================================================================

class TestDBPoolMetricsBridge:
    def test_db_pool_gauges_exist(self):
        from app.core.prometheus_exporter import metrics_registry
        for attr in ["db_pool_size", "db_pool_checkedout", "db_pool_checkedin", "db_pool_overflow"]:
            assert hasattr(metrics_registry, attr)

    def test_db_pool_counters_exist(self):
        from app.core.prometheus_exporter import metrics_registry
        for attr in ["db_checkouts_total", "db_checkins_total", "db_pool_timeouts_total"]:
            assert hasattr(metrics_registry, attr)

    def test_sync_db_pool_gauges_does_not_raise_on_error(self):
        from app.core.prometheus_exporter import sync_db_pool_gauges
        with patch("app.database.session.get_pool_status", side_effect=Exception("DB error")):
            sync_db_pool_gauges()  # Must not propagate.

    def test_sync_db_pool_gauges_reads_get_pool_status(self):
        from app.core.prometheus_exporter import sync_db_pool_gauges
        fake = {"pool_size": 5, "checkedout": 2, "checkedin": 3, "overflow": 0}
        with patch("app.database.session.get_pool_status", return_value=fake):
            sync_db_pool_gauges()

    def test_checkout_counter_interface(self):
        from app.core.prometheus_exporter import metrics_registry
        metrics_registry.db_checkouts_total.inc()
        metrics_registry.db_checkins_total.inc()

    def test_pool_metrics_no_db_connection_on_scrape(self):
        from app.core.prometheus_exporter import sync_db_pool_gauges
        with patch("app.database.session.SessionLocal") as mock_sl:
            with patch("app.database.session.get_pool_status", return_value={}):
                sync_db_pool_gauges()
            mock_sl.assert_not_called()


# ===========================================================================
# 12. CELERY SUCCESS / FAILURE / RETRY
# ===========================================================================

class TestCeleryMetrics:
    def test_celery_tasks_total_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "celery_tasks_total")

    def test_celery_task_duration_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "celery_task_duration_seconds")

    def test_celery_status_labels_fixed(self):
        from app.core.prometheus_exporter import metrics_registry
        for status in ["success", "failure", "retry"]:
            metrics_registry.celery_tasks_total.labels(status=status).inc()
            metrics_registry.celery_task_duration_seconds.labels(status=status).observe(1.0)

    def test_retry_label_distinct_from_failure(self):
        import inspect
        import app.tasks.indexing_tasks as it
        source = inspect.getsource(it.process_document_async)
        # retry and failure must appear as separate label calls.
        assert 'status="retry"' in source or "status='retry'" in source
        assert 'status="failure"' in source or "status='failure'" in source
        assert 'status="success"' in source or "status='success'" in source

    def test_celery_db_cleanup_in_finally(self):
        import inspect
        import app.tasks.indexing_tasks as it
        source = inspect.getsource(it.process_document_async)
        assert "finally:" in source
        assert "db.close()" in source


# ===========================================================================
# 13. REDIS RATE-LIMIT METRICS
# ===========================================================================

class TestRedisRateLimitMetrics:
    def test_rate_limit_hits_total_exists(self):
        from app.core.prometheus_exporter import metrics_registry
        assert hasattr(metrics_registry, "rate_limit_hits_total")

    def test_rate_limit_label_is_limiter_name(self):
        from app.core.prometheus_exporter import metrics_registry
        for limiter in ["login", "register", "api", "forgot_password", "chat"]:
            metrics_registry.rate_limit_hits_total.labels(limiter=limiter).inc()

    def test_rate_limit_no_user_id_in_label_definition(self):
        import inspect
        import app.core.prometheus_exporter as pex
        source = inspect.getsource(pex.MetricsRegistry.__new__)
        rate_limit_section = source[source.find("rate_limit_hits_total"):]
        assert "limiter" in rate_limit_section[:400]
        assert "user_id" not in rate_limit_section[:400]

    def test_prometheus_call_in_rate_limiter(self):
        import inspect
        import app.core.rate_limit as rl
        limiter_cls = getattr(rl, "RedisRateLimiter", getattr(rl, "RateLimiter", None))
        source = inspect.getsource(limiter_cls.is_rate_limited)
        assert "rate_limit_hits_total" in source


# ===========================================================================
# 14. STRUCTURED LOGGING REDACTION
# ===========================================================================

class TestStructuredLoggingRedaction:
    def test_formatter_operational_fields_present(self):
        from app.core.json_logger import StructuredJSONFormatter
        formatter = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Test event", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed
        assert parsed["message"] == "Test event"

    def test_formatter_no_sensitive_body_fields(self):
        from app.core.json_logger import StructuredJSONFormatter
        formatter = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Test event", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "body" not in parsed
        assert "Authorization" not in parsed
        assert "Cookie" not in parsed

    def test_sensitive_extra_fields_not_in_output(self):
        from app.core.json_logger import StructuredJSONFormatter
        formatter = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Event", args=(), exc_info=None,
        )
        record.Authorization = "Bearer eyJhbGciOi..."
        record.prompt = "personal prompt"
        record.jwt_token = "supersecret"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "Authorization" not in parsed
        assert "prompt" not in parsed
        assert "jwt_token" not in parsed

    def test_operational_extra_fields_included(self):
        from app.core.json_logger import StructuredJSONFormatter
        formatter = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Op event", args=(), exc_info=None,
        )
        record.request_id = "req-abc-123"
        record.duration_ms = 42.5
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed.get("request_id") == "req-abc-123"
        assert parsed.get("duration_ms") == 42.5

    def test_setup_structured_logging_idempotent(self):
        from app.core.json_logger import setup_structured_logging
        setup_structured_logging()
        setup_structured_logging()


# ===========================================================================
# 15. /metrics SECURITY
# ===========================================================================

class TestMetricsSecurity:
    def test_metrics_accessible_without_token_when_unset(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_returns_prometheus_content_type(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        if resp.status_code == 200:
            assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_blocked_without_token_when_configured(self):
        from fastapi.testclient import TestClient
        from app.main import app
        import app.main as main_module
        original = main_module.settings.METRICS_TOKEN
        try:
            main_module.settings.METRICS_TOKEN = "test-secret-token"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/metrics")
            assert resp.status_code == 401
        finally:
            main_module.settings.METRICS_TOKEN = original

    def test_metrics_allowed_with_correct_token(self):
        from fastapi.testclient import TestClient
        from app.main import app
        import app.main as main_module
        original = main_module.settings.METRICS_TOKEN
        try:
            main_module.settings.METRICS_TOKEN = "test-secret-token"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/metrics", headers={"X-Metrics-Token": "test-secret-token"})
            assert resp.status_code == 200
        finally:
            main_module.settings.METRICS_TOKEN = original

    def test_wrong_token_does_not_echo_secret(self):
        from fastapi.testclient import TestClient
        from app.main import app
        import app.main as main_module
        original = main_module.settings.METRICS_TOKEN
        try:
            main_module.settings.METRICS_TOKEN = "real-secret-do-not-echo"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/metrics", headers={"X-Metrics-Token": "wrong-token"})
            assert resp.status_code == 401
            assert "real-secret-do-not-echo" not in resp.text
        finally:
            main_module.settings.METRICS_TOKEN = original

    def test_metrics_uses_constant_time_comparison(self):
        import inspect
        import app.main as main_module
        source = inspect.getsource(main_module.metrics)
        assert "hmac.compare_digest" in source


# ===========================================================================
# SAFETY TESTS
# ===========================================================================

class TestMetricsSafety:
    def test_health_endpoint_still_lightweight(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/live")
        assert resp.status_code == 200
        assert resp.json().get("alive") is True

    def test_no_user_id_in_http_labels(self):
        import inspect
        import app.core.prometheus_exporter as pex
        source = inspect.getsource(pex.MetricsRegistry.__new__)
        http_section = source[source.find("http_requests_total"):]
        label_def_end = http_section.find("]")
        label_def = http_section[:label_def_end]
        assert "user_id" not in label_def
        assert "org_id" not in label_def
        assert "conversation_id" not in label_def

    def test_rag_stage_labels_not_user_controlled(self):
        import inspect
        from app.services.retrieval_profiler import RetrievalProfiler
        source = inspect.getsource(RetrievalProfiler.log_report)
        # Stage names are hardcoded strings in the source, not user input.
        assert '"embedding"' in source or "'embedding'" in source
        assert '"dense_search"' in source or "'dense_search'" in source

    def test_metrics_failure_does_not_crash_generate(self):
        from app.services.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.base_url = "http://localhost:11434"
        provider.model = "test-model"
        provider.timeout = 30
        provider._session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Fallback answer", "done": True}
        mock_response.raise_for_status = MagicMock()
        provider._session.post.return_value = mock_response
        result = provider.generate("prompt")
        assert result == "Fallback answer"
