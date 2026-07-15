import logging
from typing import Any

import requests
from requests.exceptions import RequestException, Timeout

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """
    Enterprise Ollama Provider.

    Handles:
    - Health checks
    - Text generation
    - Timeout handling
    - Logging
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT

    # --------------------------------------------------
    # Health Check
    # --------------------------------------------------

    def health_check(self) -> bool:
        """
        Verify Ollama server is reachable.
        """

        try:

            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=10,
            )

            response.raise_for_status()

            models = response.json().get("models", [])

            available_models = [
                model["name"]
                for model in models
            ]

            if self.model not in available_models:

                logger.error(
                    f"Configured model '{self.model}' not found."
                )

                return False

            logger.info(
                f"Ollama healthy. Model '{self.model}' available."
            )

            return True

        except Exception as ex:

            logger.exception(
                f"Ollama health check failed: {ex}"
            )

            return False

    # --------------------------------------------------
    # Generate
    # --------------------------------------------------

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

            "options": {

                "temperature": temperature,

                "num_predict": max_tokens,

            },

        }

        try:

            logger.info(
                "Sending request to Ollama..."
            )

            response = requests.post(

                f"{self.base_url}/api/generate",

                json=payload,

                timeout=self.timeout,

            )

            response.raise_for_status()

            data: dict[str, Any] = response.json()

            answer = data.get("response", "").strip()

            logger.info(
                "LLM response generated successfully."
            )

            return answer

        except Timeout:

            logger.exception(
                "Ollama request timed out."
            )

            raise

        except RequestException as ex:

            logger.exception(
                f"Ollama request failed: {ex}"
            )

            raise

        except Exception as ex:

            logger.exception(
                f"Unexpected LLM error: {ex}"
            )

            raise