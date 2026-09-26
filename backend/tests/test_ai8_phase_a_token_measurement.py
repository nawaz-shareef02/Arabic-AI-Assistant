"""
test_ai8_phase_a_token_measurement.py — AI-8 Phase A Token Measurement & Response Contract Test Suite

Verifies all 10 required Phase A criteria:
1.  non-streaming response exposes exact prompt_eval_count
2.  non-streaming response exposes exact eval_count
3.  total_tokens is derived correctly (and None when metadata unavailable)
4.  evaluation durations (prompt_eval_duration, eval_duration) are preserved
5.  streaming terminal done=true metadata is captured
6.  streaming chunks are NOT treated as token counts
7.  partial stream does not claim exact token metadata (GeneratorExit/disconnect)
8.  timeout/error does not fabricate exact token counts
9.  existing Prometheus eval_count behavior remains intact
10. existing Ollama error behavior remains intact (OllamaOverloadedException, slot release)
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from requests.exceptions import RequestException, Timeout

from app.core.prometheus_exporter import metrics_registry
from app.services.llm.base import GenerationResult, StreamingResult, TokenUsage
from app.services.llm.ollama_provider import OllamaOverloadedException, OllamaProvider


# ===========================================================================
# 1. NON-STREAMING METADATA: PROMPT_EVAL_COUNT
# ===========================================================================

class TestNonStreamingPromptEvalCount:
    def test_non_streaming_response_exposes_exact_prompt_eval_count(self):
        provider = OllamaProvider.get_instance()
        fake_data = {
            "response": "Riyadh is the capital of Saudi Arabia.",
            "prompt_eval_count": 28,
            "eval_count": 14,
            "prompt_eval_duration": 182300000,
            "eval_duration": 294100000,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_data

        with patch.object(provider._session, "post", return_value=mock_resp):
            res = provider.generate("What is the capital of Saudi Arabia?")

        assert isinstance(res, GenerationResult)
        assert isinstance(res, str)
        assert res.text == "Riyadh is the capital of Saudi Arabia."
        assert res == "Riyadh is the capital of Saudi Arabia."
        assert res.token_usage is not None
        assert res.token_usage.prompt_tokens == 28


# ===========================================================================
# 2. NON-STREAMING METADATA: EVAL_COUNT
# ===========================================================================

class TestNonStreamingEvalCount:
    def test_non_streaming_response_exposes_exact_eval_count(self):
        provider = OllamaProvider.get_instance()
        fake_data = {
            "response": "Vision 2030 is Saudi Arabia's blueprint.",
            "prompt_eval_count": 15,
            "eval_count": 52,
            "prompt_eval_duration": 95000000,
            "eval_duration": 612000000,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_data

        with patch.object(provider._session, "post", return_value=mock_resp):
            res = provider.generate("Explain Vision 2030")

        assert res.token_usage is not None
        assert res.token_usage.completion_tokens == 52


# ===========================================================================
# 3. TOTAL_TOKENS DERIVATION
# ===========================================================================

class TestTotalTokensDerivation:
    def test_total_tokens_derived_correctly_when_both_present(self):
        provider = OllamaProvider.get_instance()
        fake_data = {
            "response": "Answer",
            "prompt_eval_count": 40,
            "eval_count": 60,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_data

        with patch.object(provider._session, "post", return_value=mock_resp):
            res = provider.generate("Prompt")

        assert res.token_usage is not None
        assert res.token_usage.prompt_tokens == 40
        assert res.token_usage.completion_tokens == 60
        assert res.token_usage.total_tokens == 100
        assert res.token_usage.is_exact is True

    def test_total_tokens_none_when_counts_missing(self):
        provider = OllamaProvider.get_instance()
        fake_data = {
            "response": "Answer without counts",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_data

        with patch.object(provider._session, "post", return_value=mock_resp):
            res = provider.generate("Prompt")

        assert res.token_usage is not None
        assert res.token_usage.prompt_tokens is None
        assert res.token_usage.completion_tokens is None
        assert res.token_usage.total_tokens is None
        assert res.token_usage.is_exact is False


# ===========================================================================
# 4. EVALUATION DURATIONS PRESERVED
# ===========================================================================

class TestEvaluationDurations:
    def test_durations_preserved_in_token_usage(self):
        provider = OllamaProvider.get_instance()
        fake_data = {
            "response": "Detailed answer",
            "prompt_eval_count": 33,
            "eval_count": 77,
            "prompt_eval_duration": 450123000,
            "eval_duration": 980765000,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_data

        with patch.object(provider._session, "post", return_value=mock_resp):
            res = provider.generate("Prompt")

        assert res.token_usage is not None
        assert res.token_usage.prompt_eval_duration == 450123000
        assert res.token_usage.eval_duration == 980765000


# ===========================================================================
# 5. STREAMING TERMINAL DONE=TRUE METADATA CAPTURED
# ===========================================================================

class TestStreamingTerminalMetadata:
    def test_streaming_captures_terminal_metadata_on_normal_completion(self):
        provider = OllamaProvider.get_instance()
        fake_lines = [
            json.dumps({"response": "Saudi ", "done": False}).encode("utf-8"),
            json.dumps({"response": "Vision ", "done": False}).encode("utf-8"),
            json.dumps({"response": "2030", "done": False}).encode("utf-8"),
            json.dumps({
                "response": "",
                "done": True,
                "prompt_eval_count": 18,
                "eval_count": 42,
                "prompt_eval_duration": 120500000,
                "eval_duration": 340200000,
            }).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            stream = provider.stream_generate("Tell me about Vision 2030")
            assert isinstance(stream, StreamingResult)

            tokens = list(stream)

        assert "".join(tokens) == "Saudi Vision 2030"
        usage = stream.token_usage
        assert usage is not None
        assert usage.prompt_tokens == 18
        assert usage.completion_tokens == 42
        assert usage.total_tokens == 60
        assert usage.prompt_eval_duration == 120500000
        assert usage.eval_duration == 340200000
        assert usage.is_terminal is True
        assert usage.is_exact is True


# ===========================================================================
# 6. STREAMING CHUNKS ARE NOT TREATED AS TOKEN COUNTS
# ===========================================================================

class TestStreamingChunksNotTokenCounts:
    def test_chunk_count_differs_from_ollama_eval_count(self):
        provider = OllamaProvider.get_instance()
        # 2 textual chunks yielded, but Ollama generated 55 tokens
        fake_lines = [
            json.dumps({"response": "Chunk One ", "done": False}).encode("utf-8"),
            json.dumps({"response": "Chunk Two", "done": False}).encode("utf-8"),
            json.dumps({
                "response": "",
                "done": True,
                "prompt_eval_count": 10,
                "eval_count": 55,
            }).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            stream = provider.stream_generate("Prompt")
            tokens = list(stream)

        chunk_count = len(tokens)
        assert chunk_count == 2
        assert stream.token_usage is not None
        assert stream.token_usage.completion_tokens == 55
        assert stream.token_usage.completion_tokens != chunk_count


# ===========================================================================
# 7. PARTIAL STREAM DOES NOT CLAIM EXACT TOKEN METADATA
# ===========================================================================

class TestPartialStreamHandling:
    def test_generator_exit_sets_unavailable_metadata(self):
        provider = OllamaProvider.get_instance()
        fake_lines = [
            json.dumps({"response": f"word_{i} ", "done": False}).encode("utf-8")
            for i in range(20)
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            stream = provider.stream_generate("Prompt")
            first = next(stream)
            assert first == "word_0 "
            stream.close()  # Client disconnect / GeneratorExit

        usage = stream.token_usage
        assert usage is not None
        assert usage.is_exact is False
        assert usage.is_terminal is False
        assert usage.prompt_tokens is None
        assert usage.completion_tokens is None
        assert usage.total_tokens is None

    def test_truncated_stream_without_done_chunk(self):
        provider = OllamaProvider.get_instance()
        fake_lines = [
            json.dumps({"response": "partial text", "done": False}).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch.object(provider._session, "post", return_value=mock_resp):
            stream = provider.stream_generate("Prompt")
            tokens = list(stream)

        assert tokens == ["partial text"]
        usage = stream.token_usage
        assert usage is not None
        assert usage.is_exact is False
        assert usage.is_terminal is False
        assert usage.completion_tokens is None


# ===========================================================================
# 8. TIMEOUT AND ERROR DO NOT FABRICATE EXACT TOKEN COUNTS
# ===========================================================================

class TestTimeoutAndErrorNoFabricatedTokens:
    def test_stream_timeout_sets_inexact_usage(self):
        provider = OllamaProvider.get_instance()
        with patch.object(provider._session, "post", side_effect=Timeout("Read timed out")):
            stream = provider.stream_generate("Prompt")
            with pytest.raises(Timeout):
                next(stream)

        usage = stream.token_usage
        assert usage is not None
        assert usage.is_exact is False
        assert usage.is_terminal is False
        assert usage.prompt_tokens is None
        assert usage.completion_tokens is None

    def test_stream_network_error_sets_inexact_usage(self):
        provider = OllamaProvider.get_instance()
        with patch.object(provider._session, "post", side_effect=RequestException("Connection reset")):
            stream = provider.stream_generate("Prompt")
            with pytest.raises(RequestException):
                next(stream)

        usage = stream.token_usage
        assert usage is not None
        assert usage.is_exact is False
        assert usage.is_terminal is False
        assert usage.prompt_tokens is None
        assert usage.completion_tokens is None


# ===========================================================================
# 9. PROMETHEUS EVAL_COUNT BEHAVIOR REMAINS INTACT
# ===========================================================================

class TestPrometheusEvalCountPreserved:
    def test_prometheus_records_exact_eval_count_non_streaming(self):
        provider = OllamaProvider.get_instance()
        fake_data = {
            "response": "Response",
            "eval_count": 37,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_data

        counter = metrics_registry.llm_tokens_generated_total.labels(model=provider.model)
        with patch.object(provider._session, "post", return_value=mock_resp), \
             patch.object(counter, "inc") as mock_inc:
            provider.generate("Prompt")
            mock_inc.assert_called_once_with(37)

    def test_prometheus_records_exact_eval_count_streaming(self):
        provider = OllamaProvider.get_instance()
        fake_lines = [
            json.dumps({"response": "tok", "done": True, "eval_count": 48}).encode("utf-8"),
        ]
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = iter(fake_lines)
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        counter = metrics_registry.llm_tokens_generated_total.labels(model=provider.model)
        with patch.object(provider._session, "post", return_value=mock_resp), \
             patch.object(counter, "inc") as mock_inc:
            list(provider.stream_generate("Prompt"))
            mock_inc.assert_called_once_with(48)


# ===========================================================================
# 10. EXISTING OLLAMA ERROR BEHAVIOR REMAINS INTACT
# ===========================================================================

class TestOllamaErrorBehaviorIntact:
    def test_concurrency_ceiling_raises_overloaded_exception(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with provider._acquire_inference_slot():
            assert not provider.has_available_slot()
            with pytest.raises(OllamaOverloadedException):
                provider.generate("Prompt")

        assert provider.has_available_slot()

    def test_slot_released_on_stream_exception(self):
        provider = OllamaProvider.get_instance()
        provider.configure_concurrency(max_concurrency=1, acquire_timeout=0.0)

        with patch.object(provider._session, "post", side_effect=RequestException("Down")):
            stream = provider.stream_generate("Prompt")
            with pytest.raises(RequestException):
                next(stream)

        assert provider.has_available_slot()
