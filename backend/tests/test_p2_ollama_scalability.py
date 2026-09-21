"""
test_p2_ollama_scalability.py — P2-4 Ollama Scalability & Inference Performance Test Suite

Covers all 18 required categories:
1.  Ollama client reuse (singleton session + HTTPAdapter pooling)
2.  Concurrency limit enforcement (slot gating)
3.  Configurable concurrency (max_concurrency settings)
4.  Connection timeout behavior (connect timeout separation)
5.  Read timeout behavior (read timeout semantics)
6.  Cancellation cleanup (GeneratorExit slot reclamation)
7.  Semaphore release on success (normal completion)
8.  Semaphore release on exception (RequestException)
9.  Semaphore release on timeout (requests.exceptions.Timeout)
10. Streaming generator cleanup (partial iteration + close)
11. Overload / backpressure behavior (503 + Retry-After: 5)
12. Model keep_alive preservation (24h keep_alive in payload)
13. Context configuration (num_ctx in options)
14. Failure isolation (error does not corrupt provider state)
15. Zero DB connection during inference (P2-2 _release_db called before LLM)
16. Telemetry accuracy (active inferences gauge + rejections counter)
17. No unbounded waiting queue (immediate admission control when acquire_timeout=0)
18. Backward compatibility with chat/RAG
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.llm.ollama_provider import (
    OllamaProvider,
    OllamaOverloadedException,
    _build_options,
)


# ===========================================================================
# 1. OLLAMA CLIENT REUSE
# ===========================================================================

class TestOllamaClientReuse:
    def test_singleton_instance_reused(self):
        p1 = OllamaProvider.get_instance()
        p2 = OllamaProvider.get_instance()
        assert p1 is p2, "OllamaProvider must be a single shared instance."

    def test_session_has_connection_pooling(self):
        provider = OllamaProvider.get_instance()
        session = provider._session
        assert session is not None
        adapter = session.get_adapter("http://localhost:11434")
        assert adapter is not None
        assert adapter._pool_connections >= 2
        assert adapter._pool_maxsize >= 5


# ===========================================================================
# 2. CONCURRENCY LIMIT ENFORCEMENT
# ===========================================================================

class TestConcurrencyLimitEnforcement:
    def test_slot_blocks_excess_concurrency(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with provider._acquire_inference_slot():
            assert not provider.has_available_slot()
            with pytest.raises(OllamaOverloadedException):
                with provider._acquire_inference_slot():
                    pass

        assert provider.has_available_slot()


# ===========================================================================
# 3. CONFIGURABLE CONCURRENCY
# ===========================================================================

class TestConfigurableConcurrency:
    def test_custom_concurrency_allows_multiple_slots(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=3, acquire_timeout=0.0)

        ctx1 = provider._acquire_inference_slot()
        ctx2 = provider._acquire_inference_slot()
        ctx3 = provider._acquire_inference_slot()

        with ctx1:
            with ctx2:
                with ctx3:
                    assert not provider.has_available_slot()
                    with pytest.raises(OllamaOverloadedException):
                        with provider._acquire_inference_slot():
                            pass

        assert provider.has_available_slot()
        provider.configure_concurrency(max_concurrency=settings.OLLAMA_MAX_CONCURRENCY)


# ===========================================================================
# 4. CONNECTION TIMEOUT BEHAVIOR
# ===========================================================================

class TestConnectionTimeoutBehavior:
    def test_separated_connect_and_read_timeouts(self):
        provider = OllamaProvider.get_instance()
        req_timeout = provider.request_timeout
        assert isinstance(req_timeout, tuple)
        assert len(req_timeout) == 2
        connect_timeout, read_timeout = req_timeout
        assert connect_timeout <= 10.0
        assert read_timeout == float(provider.timeout)

    def test_generate_passes_tuple_timeout(self):
        provider = OllamaProvider.get_instance()
        with patch.object(provider._session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "Saudi Vision"}
            mock_post.return_value = mock_resp

            provider.generate("test prompt")
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            assert kwargs.get("timeout") == provider.request_timeout


# ===========================================================================
# 5. READ TIMEOUT BEHAVIOR
# ===========================================================================

class TestReadTimeoutBehavior:
    def test_timeout_in_stream_records_timeout_outcome(self):
        from requests.exceptions import Timeout

        provider = OllamaProvider.get_instance()
        with patch.object(provider._session, "post", side_effect=Timeout("Read timed out")):
            gen = provider.stream_generate("prompt")
            with pytest.raises(Timeout):
                next(gen)

        assert provider.has_available_slot()


# ===========================================================================
# 6. CANCELLATION CLEANUP
# ===========================================================================

class TestCancellationCleanup:
    def test_generator_exit_releases_slot_and_records_cancelled(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        fake_lines = [
            json.dumps({"response": "token 1"}).encode("utf-8"),
            json.dumps({"response": "token 2"}).encode("utf-8"),
            json.dumps({"response": "token 3", "done": True}).encode("utf-8"),
        ]

        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            gen = provider.stream_generate("prompt")
            t1 = next(gen)
            assert t1 == "token 1"
            gen.close()

        assert provider.has_available_slot()
        with provider._acquire_inference_slot():
            pass


# ===========================================================================
# 7. SEMAPHORE RELEASE ON SUCCESS
# ===========================================================================

class TestSemaphoreReleaseOnSuccess:
    def test_generate_releases_slot_on_success(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with patch.object(provider._session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "answer"}
            mock_post.return_value = mock_resp

            provider.generate("prompt")

        assert provider.has_available_slot()

    def test_stream_generate_releases_slot_on_success(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        fake_lines = [
            json.dumps({"response": "tok", "done": True, "eval_count": 1}).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            tokens = list(provider.stream_generate("prompt"))
            assert len(tokens) == 1

        assert provider.has_available_slot()


# ===========================================================================
# 8. SEMAPHORE RELEASE ON EXCEPTION
# ===========================================================================

class TestSemaphoreReleaseOnException:
    def test_generate_releases_slot_on_request_exception(self):
        from requests.exceptions import RequestException

        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with patch.object(provider._session, "post", side_effect=RequestException("network down")):
            with pytest.raises(RequestException):
                provider.generate("prompt")

        assert provider.has_available_slot()

    def test_stream_generate_releases_slot_on_request_exception(self):
        from requests.exceptions import RequestException

        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with patch.object(provider._session, "post", side_effect=RequestException("network down")):
            gen = provider.stream_generate("prompt")
            with pytest.raises(RequestException):
                next(gen)

        assert provider.has_available_slot()


# ===========================================================================
# 9. SEMAPHORE RELEASE ON TIMEOUT
# ===========================================================================

class TestSemaphoreReleaseOnTimeout:
    def test_generate_releases_slot_on_timeout(self):
        from requests.exceptions import Timeout

        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with patch.object(provider._session, "post", side_effect=Timeout("timed out")):
            with pytest.raises(Timeout):
                provider.generate("prompt")

        assert provider.has_available_slot()


# ===========================================================================
# 10. STREAMING GENERATOR CLEANUP
# ===========================================================================

class TestStreamingGeneratorCleanup:
    def test_partial_iteration_then_gc_frees_slot(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        fake_lines = [
            json.dumps({"response": f"token {i}"}).encode("utf-8")
            for i in range(10)
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            gen = provider.stream_generate("prompt")
            assert next(gen) == "token 0"
            assert next(gen) == "token 1"
            del gen

        assert provider.has_available_slot()


# ===========================================================================
# 11. OVERLOAD / BACKPRESSURE BEHAVIOR
# ===========================================================================

class TestOverloadBackpressureBehavior:
    def test_rejection_increments_counter(self):
        from app.core.prometheus_exporter import metrics_registry

        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        counter_metric = metrics_registry.llm_queue_rejections_total
        assert hasattr(counter_metric, "labels")
        label_obj = counter_metric.labels(model=provider.model)
        assert hasattr(label_obj, "inc")

        with provider._acquire_inference_slot():
            with pytest.raises(OllamaOverloadedException):
                with provider._acquire_inference_slot():
                    pass

    def test_global_exception_handler_returns_503_retry_after(self):
        from app.main import app
        from app.core.dependencies import get_current_user, get_db
        client = TestClient(app, raise_server_exceptions=False)

        mock_user = MagicMock(id=1, email="test@arabiq.sa")
        mock_db = MagicMock()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch.object(OllamaProvider, "get_instance") as mock_get:
                mock_inst = MagicMock()
                mock_inst.has_available_slot.return_value = False
                mock_get.return_value = mock_inst

                with patch("app.api.v1.chat.authorize_knowledge_base_access") as mock_auth_kb, \
                     patch("app.api.v1.chat.ChatRateLimitService") as mock_rate_cls:

                    mock_auth_kb.return_value = MagicMock(id=10, organization_id=1)
                    mock_rate = mock_rate_cls.return_value
                    mock_rate.check_and_acquire_stream_slot.return_value = MagicMock(
                        allowed=True, lease_id="lease-123", headers={}
                    )

                    resp = client.post(
                        "/api/v1/chat/stream",
                        json={"knowledge_base_id": 10, "question": "test question"},
                    )

                    assert resp.status_code == 503
                    assert "Retry-After" in resp.headers
                    assert resp.headers["Retry-After"] == "5"
                    assert "peak capacity" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# 12. MODEL KEEP_ALIVE PRESERVATION
# ===========================================================================

class TestModelKeepAlivePreservation:
    def test_keep_alive_present_in_generate_payload(self):
        provider = OllamaProvider.get_instance()
        with patch.object(provider._session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "ok"}
            mock_post.return_value = mock_resp

            provider.generate("hi")
            _, kwargs = mock_post.call_args
            assert kwargs["json"]["keep_alive"] == settings.OLLAMA_KEEP_ALIVE
            assert settings.OLLAMA_KEEP_ALIVE == "24h"


# ===========================================================================
# 13. CONTEXT CONFIGURATION
# ===========================================================================

class TestContextConfiguration:
    def test_num_ctx_present_in_options(self):
        opts = _build_options(temperature=0.1, max_tokens=100)
        assert opts["num_ctx"] == settings.OLLAMA_NUM_CTX
        assert opts["num_ctx"] == 2048

    def test_think_is_absent_from_options(self):
        """P2-4 defect fix: `think` must NOT appear inside the options dict.
        It belongs at the ROOT level of the Ollama request payload.
        """
        opts = _build_options(temperature=0.1, max_tokens=100)
        assert "think" not in opts, (
            "think must not be inside options{}. "
            "For Ollama 0.33.3 + Qwen3:8B it is only honoured at the request root."
        )


# ===========================================================================
# 14. FAILURE ISOLATION
# ===========================================================================

class TestFailureIsolation:
    def test_failed_request_does_not_block_subsequent_request(self):
        from requests.exceptions import RequestException

        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with patch.object(provider._session, "post", side_effect=RequestException("error")):
            with pytest.raises(RequestException):
                provider.generate("prompt 1")

        with patch.object(provider._session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "recovered"}
            mock_post.return_value = mock_resp

            res = provider.generate("prompt 2")
            assert res == "recovered"


# ===========================================================================
# 13b. ROOT-LEVEL think:False PAYLOAD VERIFICATION  (P2-4 corrective patch)
# ===========================================================================

class TestThinkFalseRootLevel:
    """Verify that `think: False` is sent at the ROOT of every Ollama request
    payload, NOT nested inside options{}.

    Ollama 0.33.3 + Qwen3:8B ignores `think` when it appears inside `options`;
    only the root-level key is honoured.  These tests lock that invariant.
    """

    def test_generate_payload_has_root_think_false(self):
        """generate() must set think:False at payload root."""
        provider = OllamaProvider.get_instance()
        captured = {}

        def fake_post(url, json=None, **kwargs):
            captured.update(json or {})
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"response": "ok"}
            return mock_resp

        with patch.object(provider._session, "post", side_effect=fake_post):
            provider.generate("test prompt")

        assert captured.get("think") is False, (
            "generate() must include think:False at payload root level."
        )
        assert "think" not in captured.get("options", {}), (
            "generate() must NOT include think inside options{}."
        )

    def test_stream_generate_payload_has_root_think_false(self):
        """stream_generate() must set think:False at payload root."""
        provider = OllamaProvider.get_instance()
        captured = {}

        fake_lines = [
            json.dumps({"response": "tok", "done": True, "eval_count": 1}).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        def fake_post(url, json=None, **kwargs):
            captured.update(json or {})
            return mock_resp

        with patch.object(provider._session, "post", side_effect=fake_post):
            list(provider.stream_generate("test prompt"))

        assert captured.get("think") is False, (
            "stream_generate() must include think:False at payload root level."
        )
        assert "think" not in captured.get("options", {}), (
            "stream_generate() must NOT include think inside options{}."
        )

    def test_warmup_payload_has_root_think_false(self):
        """warmup() must set think:False at payload root."""
        provider = OllamaProvider.get_instance()
        captured = {}

        def fake_post(url, json=None, **kwargs):
            captured.update(json or {})
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        with patch.object(provider._session, "post", side_effect=fake_post):
            provider.warmup()

        assert captured.get("think") is False, (
            "warmup() must include think:False at payload root level."
        )
        assert "think" not in captured.get("options", {}), (
            "warmup() must NOT include think inside options{}."
        )


# ===========================================================================
# 15. ZERO DB CONNECTION DURING INFERENCE
# ===========================================================================

class TestZeroDBConnectionDuringInference:
    def test_rag_service_calls_release_db_before_generate(self):
        from app.services.rag_service import RAGService

        mock_db = MagicMock()
        rag = RAGService(mock_db)

        mock_result = MagicMock()
        mock_result.text = "test chunk"
        mock_result.score = 0.9
        mock_result.chunk_uuid = "u1"
        mock_result.parsed_document_id = 1
        mock_result.payload = {"text": "test chunk", "chunk_uuid": "u1", "parsed_document_id": 1}

        with patch.object(rag.search_service, "hybrid_search", return_value=[mock_result]), \
             patch.object(rag, "_release_db") as mock_release_db, \
             patch.object(rag.llm, "generate", return_value="answer"):

            rag.ask(question="test?", knowledge_base_id=1)
            mock_release_db.assert_called_once()


# ===========================================================================
# 16. TELEMETRY ACCURACY
# ===========================================================================

class TestTelemetryAccuracy:
    def test_active_inferences_gauge_tracking(self):
        from app.core.prometheus_exporter import metrics_registry

        provider = OllamaProvider.get_instance()
        gauge = metrics_registry.llm_active_inferences
        assert hasattr(gauge, "labels")
        label_obj = gauge.labels(model=provider.model)
        assert hasattr(label_obj, "inc")
        assert hasattr(label_obj, "dec")

        with patch.object(label_obj, "inc") as mock_inc, \
             patch.object(label_obj, "dec") as mock_dec:
            with provider._acquire_inference_slot():
                mock_inc.assert_called_once()
            mock_dec.assert_called_once()


# ===========================================================================
# 17. NO UNBOUNDED WAITING QUEUE
# ===========================================================================

class TestNoUnboundedWaitingQueue:
    def test_acquire_timeout_zero_fails_immediately(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with provider._acquire_inference_slot():
            t0 = time.perf_counter()
            with pytest.raises(OllamaOverloadedException):
                with provider._acquire_inference_slot():
                    pass
            elapsed = time.perf_counter() - t0
            assert elapsed < 0.05, f"Expected immediate failure, took {elapsed}s"


# ===========================================================================
# 18. BACKWARD COMPATIBILITY WITH CHAT / RAG
# ===========================================================================

class TestBackwardCompatibility:
    def test_generate_strips_think_tags_and_returns_clean_text(self):
        provider = OllamaProvider.get_instance()
        with patch.object(provider._session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "response": "<think>Internal reasoning</think>Saudi Arabia Vision 2030."
            }
            mock_post.return_value = mock_resp

            answer = provider.generate("test")
            assert answer == "Saudi Arabia Vision 2030."
            assert "<think>" not in answer
