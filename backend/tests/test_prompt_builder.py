import pytest
from app.services.prompt_builder import PromptBuilder


def test_prompt_builder():
    """Test PromptBuilder constructs grounded prompt with context."""
    contexts = [
        "Saudi Vision 2030 focuses on AI and digital transformation.",
        "ArabIQ is an enterprise AI platform.",
    ]
    prompt = PromptBuilder.build_prompt(
        question="What is Saudi Vision 2030?",
        contexts=contexts,
    )

    assert "Saudi Vision 2030" in prompt
    assert "ArabIQ" in prompt