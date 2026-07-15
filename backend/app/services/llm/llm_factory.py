import logging

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class LLMFactory:
    """
    Enterprise LLM Factory.

    Responsible for creating the configured LLM provider.
    """

    @staticmethod
    def get_provider() -> BaseLLMProvider:

        provider = settings.LLM_PROVIDER.lower()

        logger.info(f"Loading LLM Provider: {provider}")

        if provider == "ollama":
            return OllamaProvider()

        raise ValueError(
            f"Unsupported LLM Provider: {settings.LLM_PROVIDER}"
        )