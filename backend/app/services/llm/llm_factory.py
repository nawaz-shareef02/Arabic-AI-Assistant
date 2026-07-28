import logging
import threading

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton cache — provider created exactly once.
# ---------------------------------------------------------------------------
_provider: BaseLLMProvider | None = None
_provider_lock = threading.Lock()
_init_count: int = 0


class LLMFactory:
    """
    Enterprise LLM Factory — Singleton Cache Pattern.

    Guarantees:
    - The LLM provider is instantiated exactly once for the entire process
      lifetime, regardless of how many times ``get_provider()`` is called.
    - Thread-safe double-checked locking prevents race conditions.
    - Initialization count is logged:
        "LLMFactory initialized provider (1)"   ← correct
        "LLMFactory initialized provider (2)"   ← should never appear.
    """

    @staticmethod
    def get_provider() -> BaseLLMProvider:
        global _provider, _init_count

        # Fast path: provider already cached.
        if _provider is not None:
            return _provider

        # Slow path: create provider under lock, then cache it.
        with _provider_lock:
            if _provider is None:
                _init_count += 1
                provider_name = settings.LLM_PROVIDER.lower()
                logger.info(
                    f"LLMFactory initialized provider ({_init_count}) "
                    f"— provider={provider_name}  model={settings.LLM_MODEL}"
                )

                if provider_name == "ollama":
                    # Delegate to OllamaProvider's own singleton accessor.
                    _provider = OllamaProvider.get_instance()
                else:
                    raise ValueError(
                        f"Unsupported LLM Provider: {settings.LLM_PROVIDER}"
                    )

        return _provider