from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TokenUsage:
    """
    Authoritative provider-level token metadata.
    Exposes raw LLM provider metrics without quota or billing logic.
    """
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_duration: Optional[int] = None
    is_terminal: bool = True
    is_exact: bool = True


class GenerationResult(str):
    """
    Standardized provider-level generation result.
    Subclasses str for 100% backward compatibility with all existing callers
    and assertions expecting a string, while exposing .text, .token_usage, and .model.
    """
    text: str
    token_usage: Optional[TokenUsage]
    model: Optional[str]

    def __new__(
        cls,
        text: str,
        token_usage: Optional[TokenUsage] = None,
        model: Optional[str] = None,
    ):
        obj = super().__new__(cls, text)
        obj.text = text
        obj.token_usage = token_usage
        obj.model = model
        return obj

    def __repr__(self) -> str:
        return (
            f"GenerationResult(text={self.text!r}, "
            f"token_usage={self.token_usage!r}, "
            f"model={self.model!r})"
        )


class StreamingResult(Generator):
    """
    Standardized provider-level streaming result wrapping a token generator.
    Implements the standard Python Generator protocol (yields string tokens),
    while exposing .token_usage and .model upon completion or interruption.
    """

    def __init__(
        self,
        generator: Optional[Any] = None,
        model: Optional[str] = None,
        usage_box: Optional[list[Optional[TokenUsage]]] = None,
    ) -> None:
        self._gen = generator
        self.model = model
        self._usage_box: list[Optional[TokenUsage]] = (
            usage_box if usage_box is not None else [None]
        )

    @property
    def token_usage(self) -> Optional[TokenUsage]:
        return self._usage_box[0]

    @token_usage.setter
    def token_usage(self, value: Optional[TokenUsage]) -> None:
        self._usage_box[0] = value

    def set_generator(self, generator: Any) -> None:
        self._gen = generator

    def __iter__(self) -> "StreamingResult":
        return self

    def __next__(self) -> str:
        if self._gen is None:
            raise StopIteration
        return next(self._gen)

    def send(self, value: Any) -> str:
        if self._gen is None:
            raise StopIteration
        return self._gen.send(value)

    def throw(self, typ: Any, val: Any = None, tb: Any = None) -> Any:
        if self._gen is not None and hasattr(self._gen, "throw"):
            return self._gen.throw(typ, val, tb)
        raise typ(val)

    def close(self) -> None:
        if self._gen is not None and hasattr(self._gen, "close"):
            self._gen.close()

    def __del__(self) -> None:
        self.close()



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
        Returns a GenerationResult (which subclasses str for complete compatibility).
        """
        pass