import json
import logging
import threading
import time
from typing import Any, Generator

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout
from urllib3.util.retry import Retry

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state — one instance, one HTTP session, for the process lifetime.
# ---------------------------------------------------------------------------
_instance: "OllamaProvider | None" = None
_instance_lock = threading.Lock()
_init_count: int = 0


def _build_session() -> requests.Session:
    """
    Build a persistent requests.Session with connection pooling.
    Eliminates per-request TCP handshake overhead to Ollama.
    """
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=4,   # bumped from 2 — supports light concurrency
        pool_maxsize=10,
        max_retries=retry,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _build_options(
    temperature: float,
    max_tokens: int,
) -> dict:
    """
    Build the Ollama options dict (model sampling parameters only).

    NOTE: "think" is intentionally NOT placed here.
    For Ollama 0.33.3 + Qwen3:8B, `think` must be a ROOT-level key in the
    request payload — nesting it inside `options{}` is silently ignored,
    causing the model to run full chain-of-thought reasoning and potentially
    return an empty visible response while consuming the thinking budget.
    Each call site (warmup, generate, stream_generate) sets `"think": False`
    directly on the payload dict.
    """
    opts: dict = {
        "temperature": temperature,
        "num_predict": max_tokens,
        "num_ctx": settings.OLLAMA_NUM_CTX,
    }
    if settings.OLLAMA_NUM_THREAD > 0:
        opts["num_thread"] = settings.OLLAMA_NUM_THREAD
    return opts


def _strip_think_tags(text: str) -> str:
    """
    Defensive fallback: strip residual <think>...</think> blocks that may
    appear if an older Ollama version ignores the 'think' option.
    """
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class OllamaOverloadedException(Exception):
    """Raised when Ollama inference concurrency ceiling is reached and no slot is available."""
    pass


class _InferenceSlotContext:
    """
    Context manager guaranteeing bounded inference concurrency and clean slot release.
    Guarantees:
    - Slot acquired on __enter__ or raises OllamaOverloadedException.
    - Slot released on __exit__ in all paths (success, exception, timeout, cancellation).
    - Cannot release more times than acquired.
    """
    def __init__(self, provider: "OllamaProvider"):
        self.provider = provider
        self.acquired = False

    def __enter__(self):
        acquire_timeout = getattr(self.provider, "acquire_timeout", 0.0)
        semaphore = getattr(self.provider, "_semaphore", None)
        if semaphore is None:
            max_c = max(1, getattr(self.provider, "max_concurrency", 1))
            semaphore = threading.BoundedSemaphore(value=max_c)
            self.provider._semaphore = semaphore

        blocking = acquire_timeout > 0
        timeout = acquire_timeout if blocking else None

        if blocking:
            self.acquired = semaphore.acquire(blocking=True, timeout=timeout)
        else:
            self.acquired = semaphore.acquire(blocking=False)

        if not self.acquired:
            model_name = getattr(self.provider, "model", "qwen3:8b")
            max_c = getattr(self.provider, "max_concurrency", 1)
            try:
                from app.core.prometheus_exporter import metrics_registry
                metrics_registry.llm_queue_rejections_total.labels(model=model_name).inc()
            except Exception:
                pass
            logger.warning(
                f"Ollama inference rejected: concurrency limit ({max_c}) reached."
            )
            raise OllamaOverloadedException(
                "The AI inference engine is currently at peak capacity. Please retry shortly."
            )

        try:
            from app.core.prometheus_exporter import metrics_registry
            model_name = getattr(self.provider, "model", "qwen3:8b")
            metrics_registry.llm_active_inferences.labels(model=model_name).inc()
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            semaphore = getattr(self.provider, "_semaphore", None)
            if semaphore is not None:
                semaphore.release()
            self.acquired = False
            try:
                from app.core.prometheus_exporter import metrics_registry
                model_name = getattr(self.provider, "model", "qwen3:8b")
                metrics_registry.llm_active_inferences.labels(model=model_name).dec()
            except Exception:
                pass
        return False


class OllamaProvider(BaseLLMProvider):
    """
    Enterprise Ollama Provider — Singleton Pattern.

    Key performance characteristics:
    - Exactly one instance for the entire process lifetime.
    - Single persistent requests.Session reused across all requests.
    - Model pinned in Ollama's memory via keep_alive (no cold-load penalty).
    - qwen3 thinking mode disabled via 'think: false' (eliminates 2-5 min
      silence before first token on CPU).
    - Initialization count logged to verify singleton guarantee.
    - Bounded inference concurrency via process-local BoundedSemaphore.
    - Separated connect/read timeouts to fail fast if Ollama daemon is down.
    """

    max_concurrency: int = 1
    acquire_timeout: float = 0.0
    _semaphore: threading.BoundedSemaphore | None = None

    def __init__(self):
        global _init_count
        _init_count += 1
        self.base_url = settings.OLLAMA_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self._session = _build_session()
        self.max_concurrency = max(1, getattr(settings, "OLLAMA_MAX_CONCURRENCY", 1))
        self.acquire_timeout = max(0.0, getattr(settings, "OLLAMA_ACQUIRE_TIMEOUT", 0.0))
        self._semaphore = threading.BoundedSemaphore(value=self.max_concurrency)
        logger.info(
            f"OllamaProvider initialized ({_init_count}) "
            f"— model={self.model}  keep_alive={settings.OLLAMA_KEEP_ALIVE}  "
            f"max_concurrency={self.max_concurrency}  acquire_timeout={self.acquire_timeout}s  think=False"
        )

    @property
    def request_timeout(self) -> tuple[float, float]:
        """
        Separates connection timeout from read timeout.
        connect_timeout: max 10s (fail-fast if Ollama daemon is down/unreachable).
        read_timeout: self.timeout (180s) between incoming token chunks.
        """
        connect_timeout = min(10.0, float(self.timeout))
        read_timeout = float(self.timeout)
        return (connect_timeout, read_timeout)

    def _acquire_inference_slot(self) -> _InferenceSlotContext:
        """Acquires a concurrency slot or raises OllamaOverloadedException."""
        return _InferenceSlotContext(self)

    def has_available_slot(self) -> bool:
        """Check if an inference slot is currently free without reserving it."""
        acquired = self._semaphore.acquire(blocking=False)
        if acquired:
            self._semaphore.release()
            return True
        return False

    def configure_concurrency(self, max_concurrency: int, acquire_timeout: float = 0.0) -> None:
        """Dynamically reconfigure concurrency limits (primarily for testing and benchmarks)."""
        self.max_concurrency = max(1, max_concurrency)
        self.acquire_timeout = max(0.0, acquire_timeout)
        self._semaphore = threading.BoundedSemaphore(value=self.max_concurrency)

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "OllamaProvider":
        """Return the shared singleton, creating it on first call."""
        global _instance
        if _instance is None:
            with _instance_lock:
                if _instance is None:
                    _instance = cls()
        return _instance

    # ------------------------------------------------------------------
    # Warmup — pre-loads the model into Ollama's memory.
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """
        Send a minimal 1-token generation to Ollama so LLM weights are
        loaded into RAM before the first real user request.
        `think: False` is set at ROOT level of the payload (not inside options)
        to correctly suppress Qwen3 chain-of-thought on Ollama 0.33.3+.
        """
        logger.info(f"OllamaProvider warmup: pre-loading model '{self.model}' into memory...")
        t0 = time.perf_counter()
        try:
            payload = {
                "model": self.model,
                "prompt": "hi",
                "stream": False,
                "think": False,  # ROOT-level — correctly suppresses Qwen3 thinking on Ollama 0.33.3
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": _build_options(
                    temperature=0.0,
                    max_tokens=1,
                ),
            }
            resp = self._session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(f"OllamaProvider warmup complete — model loaded in {elapsed:.0f} ms")
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                f"OllamaProvider warmup failed after {elapsed:.0f} ms: {exc}. "
                "First real request may be slower."
            )

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        try:
            response = self._session.get(
                f"{self.base_url}/api/tags",
                timeout=10,
            )
            response.raise_for_status()

            models = response.json().get("models", [])
            available_models = [model["name"] for model in models]

            if self.model not in available_models:
                logger.error(f"Configured model '{self.model}' not found in Ollama.")
                return False

            logger.info(f"Ollama healthy. Model '{self.model}' available.")
            return True

        except Exception as ex:
            logger.exception(f"Ollama health check failed: {ex}")
            return False

    # ------------------------------------------------------------------
    # Generate (non-streaming)
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        temperature: float = settings.LLM_TEMPERATURE,
        max_tokens: int = settings.LLM_MAX_TOKENS,
    ) -> str:
        with self._acquire_inference_slot():
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "think": False,  # ROOT-level — correctly suppresses Qwen3 thinking on Ollama 0.33.3
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": _build_options(
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
            }

            t0 = time.perf_counter()
            try:
                logger.info("Sending request to Ollama (non-streaming, think=False)...")

                response = self._session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.request_timeout,
                )
                response.raise_for_status()

                data: dict[str, Any] = response.json()
                answer = _strip_think_tags(data.get("response", ""))

                # Instrument: success path.
                try:
                    from app.core.prometheus_exporter import metrics_registry
                    duration = time.perf_counter() - t0
                    metrics_registry.llm_requests_total.labels(
                        model=self.model, outcome="success"
                    ).inc()
                    metrics_registry.llm_generation_duration_seconds.labels(
                        model=self.model
                    ).observe(duration)
                    # Ollama returns eval_count (generated tokens) in the response.
                    # Use it when available — no secondary tokenization.
                    eval_count = data.get("eval_count")
                    if isinstance(eval_count, int) and eval_count > 0:
                        metrics_registry.llm_tokens_generated_total.labels(
                            model=self.model
                        ).inc(eval_count)
                except Exception:
                    pass  # Never fail LLM generation due to metrics error.

                logger.info("LLM response generated successfully.")
                return answer

            except Timeout:
                try:
                    from app.core.prometheus_exporter import metrics_registry
                    metrics_registry.llm_requests_total.labels(
                        model=self.model, outcome="timeout"
                    ).inc()
                except Exception:
                    pass
                logger.exception("Ollama request timed out.")
                raise

            except RequestException as ex:
                try:
                    from app.core.prometheus_exporter import metrics_registry
                    metrics_registry.llm_requests_total.labels(
                        model=self.model, outcome="error"
                    ).inc()
                except Exception:
                    pass
                logger.exception(f"Ollama request failed: {ex}")
                raise

            except Exception as ex:
                try:
                    from app.core.prometheus_exporter import metrics_registry
                    metrics_registry.llm_requests_total.labels(
                        model=self.model, outcome="error"
                    ).inc()
                except Exception:
                    pass
                logger.exception(f"Unexpected LLM error: {ex}")
                raise


    # ------------------------------------------------------------------
    # Stream Generate
    # ------------------------------------------------------------------

    def stream_generate(
        self,
        prompt: str,
        temperature: float = settings.LLM_TEMPERATURE,
        max_tokens: int = settings.LLM_MAX_TOKENS,
    ) -> Generator[str, None, None]:
        """
        Stream tokens from Ollama.

        think=False eliminates qwen3's chain-of-thought pre-generation,
        cutting first-token latency from 2-5 minutes to 2-5 seconds on CPU.

        A stateful <think> tag filter is applied as a defensive layer in case
        an older Ollama version ignores the 'think' option.

        Metrics recorded:
        - TTFT: time from request start to first real token yielded.
        - Generation duration: request start to last token yielded.
        - Outcome: success | timeout | error | cancelled (GeneratorExit).
        - Token count: from Ollama eval_count on final done=true chunk.
        """
        with self._acquire_inference_slot():
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "think": False,  # ROOT-level — correctly suppresses Qwen3 thinking on Ollama 0.33.3
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": _build_options(
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
            }

            t0 = time.perf_counter()
            outcome = "success"  # updated in except blocks before re-raise
            first_token_recorded = False
            eval_count: int = 0  # from Ollama final chunk

            try:
                logger.info("Starting Ollama streaming (think=False)...")

                with self._session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=self.request_timeout,
                ) as response:

                    response.raise_for_status()

                    # Stateful <think> block filter — buffers tokens inside a
                    # <think> block and discards them, yielding only real answer
                    # tokens. This is a defensive layer; with think=False Ollama
                    # should not emit any <think> tokens at all.
                    inside_think = False
                    think_buf = ""

                    for line in response.iter_lines():
                        if not line:
                            continue

                        chunk = json.loads(line.decode("utf-8"))
                        token = chunk.get("response", "")

                        # Capture token count from final chunk (done=true).
                        if chunk.get("done"):
                            ec = chunk.get("eval_count")
                            if isinstance(ec, int) and ec > 0:
                                eval_count = ec

                        if not token:
                            continue

                        # --- think-tag filtering ---
                        if inside_think:
                            think_buf += token
                            if "</think>" in think_buf:
                                # Emit everything AFTER the closing tag.
                                after = think_buf.split("</think>", 1)[1]
                                inside_think = False
                                think_buf = ""
                                if after:
                                    if not first_token_recorded:
                                        try:
                                            from app.core.prometheus_exporter import metrics_registry
                                            metrics_registry.llm_first_token_seconds.labels(
                                                model=self.model
                                            ).observe(time.perf_counter() - t0)
                                        except Exception:
                                            pass
                                        first_token_recorded = True
                                    yield after
                            continue

                        if "<think>" in token:
                            parts = token.split("<think>", 1)
                            if parts[0]:
                                if not first_token_recorded:
                                    try:
                                        from app.core.prometheus_exporter import metrics_registry
                                        metrics_registry.llm_first_token_seconds.labels(
                                            model=self.model
                                        ).observe(time.perf_counter() - t0)
                                    except Exception:
                                        pass
                                    first_token_recorded = True
                                yield parts[0]
                            inside_think = True
                            think_buf = parts[1] if len(parts) > 1 else ""
                            # Check if the think block also closes on the same token.
                            if "</think>" in think_buf:
                                after = think_buf.split("</think>", 1)[1]
                                inside_think = False
                                think_buf = ""
                                if after:
                                    yield after
                            continue

                        # Normal token — record TTFT on first, then yield.
                        if not first_token_recorded:
                            try:
                                from app.core.prometheus_exporter import metrics_registry
                                metrics_registry.llm_first_token_seconds.labels(
                                    model=self.model
                                ).observe(time.perf_counter() - t0)
                            except Exception:
                                pass
                            first_token_recorded = True
                        yield token

                logger.info("Streaming completed successfully.")

            except GeneratorExit:
                # Caller cancelled the generator (client disconnect, stream lease expired).
                outcome = "cancelled"
                # Do not re-raise — GeneratorExit is handled by the generator protocol.

            except Timeout:
                outcome = "timeout"
                logger.exception("Streaming request timed out.")
                raise

            except RequestException as ex:
                outcome = "error"
                logger.exception(f"Streaming request failed: {ex}")
                raise

            except Exception as ex:
                outcome = "error"
                logger.exception(f"Unexpected streaming error: {ex}")
                raise

            finally:
                # Record outcome metrics. Never fails generation.
                try:
                    from app.core.prometheus_exporter import metrics_registry
                    duration = time.perf_counter() - t0
                    metrics_registry.llm_requests_total.labels(
                        model=self.model, outcome=outcome
                    ).inc()
                    metrics_registry.llm_generation_duration_seconds.labels(
                        model=self.model
                    ).observe(duration)
                    if eval_count > 0:
                        metrics_registry.llm_tokens_generated_total.labels(
                            model=self.model
                        ).inc(eval_count)
                except Exception:
                    pass

