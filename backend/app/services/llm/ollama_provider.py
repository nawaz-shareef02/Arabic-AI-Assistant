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
    *,
    thinking: bool = False,
) -> dict:
    """
    Build the Ollama options dict.

    CRITICAL — qwen3 and deepseek-r1 both ship with thinking (chain-of-thought)
    mode ENABLED by default. When active, the model silently generates hundreds
    of <think>...</think> tokens BEFORE the first visible response token.
    On CPU this translates to minutes of dead silence before the user sees anything.

    Setting "think": False disables this completely. The streaming layer also
    has a stateful <think> tag filter as a defensive fallback.
    """
    opts: dict = {
        "temperature": temperature,
        "num_predict": max_tokens,
        "num_ctx": settings.OLLAMA_NUM_CTX,
        # Disable thinking mode for qwen3 — the single most impactful
        # latency fix for this model family.
        "think": thinking,
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
    """

    def __init__(self):
        global _init_count
        _init_count += 1
        self.base_url = settings.OLLAMA_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self._session = _build_session()
        logger.info(
            f"OllamaProvider initialized ({_init_count}) "
            f"— model={self.model}  keep_alive={settings.OLLAMA_KEEP_ALIVE}  think=False"
        )

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
        Thinking mode is disabled even here to verify the option works.
        """
        logger.info(f"OllamaProvider warmup: pre-loading model '{self.model}' into memory...")
        t0 = time.perf_counter()
        try:
            payload = {
                "model": self.model,
                "prompt": "hi",
                "stream": False,
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": _build_options(
                    temperature=0.0,
                    max_tokens=1,
                    thinking=False,
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

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": _build_options(
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=False,
            ),
        }

        try:
            logger.info("Sending request to Ollama (non-streaming, think=False)...")

            response = self._session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data: dict[str, Any] = response.json()
            answer = _strip_think_tags(data.get("response", ""))

            logger.info("LLM response generated successfully.")
            return answer

        except Timeout:
            logger.exception("Ollama request timed out.")
            raise

        except RequestException as ex:
            logger.exception(f"Ollama request failed: {ex}")
            raise

        except Exception as ex:
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
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": _build_options(
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=False,
            ),
        }

        try:
            logger.info("Starting Ollama streaming (think=False)...")

            with self._session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=self.timeout,
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
                                yield after
                        continue

                    if "<think>" in token:
                        parts = token.split("<think>", 1)
                        if parts[0]:
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

                    # Normal token — yield immediately.
                    yield token

            logger.info("Streaming completed successfully.")

        except Timeout:
            logger.exception("Streaming request timed out.")
            raise

        except RequestException as ex:
            logger.exception(f"Streaming request failed: {ex}")
            raise

        except Exception as ex:
            logger.exception(f"Unexpected streaming error: {ex}")
            raise