import pytest
from app.services.llm import LLMFactory


def test_llm_factory():
    """Test LLMFactory resolves the configured provider implementing BaseLLMProvider."""
    provider = LLMFactory.get_provider()
    assert provider is not None
    assert hasattr(provider, "generate")
    assert hasattr(provider, "health_check")