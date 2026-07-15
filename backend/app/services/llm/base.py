from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """
    Base interface for all LLM providers.

    Every provider (Ollama, OpenAI, Azure, Gemini...)
    must implement this interface.
    """

    @abstractmethod
    def health_check(self) -> bool:
        """
        Returns True if provider is available.
        """
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """
        Generate response from LLM.
        """
        pass