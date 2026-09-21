# pyrefly: ignore-file
"""
FTS Normalizer & Strategy Module for AI-3B.1 Experimentation.

INTERNAL / EXPERIMENTAL ONLY — NOT EXPOSED TO PRODUCTION APIS OR PUBLIC CALLERS.

Provides query preprocessing and PostgreSQL tsquery construction for the 4
controlled benchmark strategies:
- Strategy A: BASELINE              — plainto_tsquery("simple", query)
- Strategy B: STOPWORD_STRIPPED     — plainto_tsquery("simple", stripped_query)
- Strategy C: WEBSEARCH_NORMALIZED  — websearch_to_tsquery("simple", stripped_query)
- Strategy D: WEBSEARCH_RAW         — websearch_to_tsquery("simple", query)
"""

import re
from enum import Enum
from typing import Any
from sqlalchemy import func


class FTSStrategy(str, Enum):
    BASELINE = "BASELINE"
    STOPWORD_STRIPPED = "STOPWORD_STRIPPED"
    WEBSEARCH_NORMALIZED = "WEBSEARCH_NORMALIZED"
    WEBSEARCH_RAW = "WEBSEARCH_RAW"


# Leading question phrases / tokens (case-insensitive, checked longest first)
_EN_QUESTION_PREFIXES = [
    r"^can\s+you\s+tell\s+me\s+about\b",
    r"^can\s+you\s+explain\b",
    r"^tell\s+me\s+about\b",
    r"^please\s+explain\b",
    r"^explain\b",
    r"^what\s+is\b",
    r"^what\s+are\b",
    r"^what\s+was\b",
    r"^what\s+were\b",
    r"^what\s+does\b",
    r"^what\s+do\b",
    r"^what\s+did\b",
    r"^what\s+can\b",
    r"^what\b",
    r"^how\s+does\b",
    r"^how\s+do\b",
    r"^how\s+did\b",
    r"^how\s+is\b",
    r"^how\s+are\b",
    r"^how\s+can\b",
    r"^how\s+to\b",
    r"^how\b",
    r"^why\s+does\b",
    r"^why\s+do\b",
    r"^why\s+is\b",
    r"^why\s+are\b",
    r"^why\b",
    r"^which\s+is\b",
    r"^which\s+are\b",
    r"^which\b",
    r"^where\s+is\b",
    r"^where\s+are\b",
    r"^where\s+does\b",
    r"^where\s+do\b",
    r"^where\b",
    r"^who\s+is\b",
    r"^who\s+are\b",
    r"^who\b",
    r"^when\s+is\b",
    r"^when\s+does\b",
    r"^when\b",
    r"^can\s+you\b",
    r"^please\b",
]

_AR_QUESTION_PREFIXES = [
    r"^اشرح\s+لي\b",
    r"^اشرح\b",
    r"^وضح\s+لي\b",
    r"^وضح\b",
    r"^صف\s+لي\b",
    r"^صف\b",
    r"^ما\s+هي\b",
    r"^ما\s+هو\b",
    r"^ماذا\b",
    r"^ما\b",
    r"^كيف\s+يتم\b",
    r"^كيف\s+يمكن\b",
    r"^كيف\b",
    r"^لماذا\b",
    r"^أين\s+يقع\b",
    r"^أين\s+توجد\b",
    r"^أين\s+يوجد\b",
    r"^أين\b",
    r"^اين\b",
    r"^هل\s+يمكن\b",
    r"^هل\s+يجب\b",
    r"^هل\b",
    r"^كم\s+عدد\b",
    r"^كم\s+نسبة\b",
    r"^كم\b",
]

_COMPILED_PREFIXES = [
    re.compile(p, re.IGNORECASE) for p in (_EN_QUESTION_PREFIXES + _AR_QUESTION_PREFIXES)
]


def strip_question_tokens(query: str) -> str:
    """
    Deterministically strips leading conversational question tokens and trailing
    punctuation from an Arabic or English retrieval query.

    If stripping results in an empty string, falls back to the original trimmed query.
    """
    original = query.strip()
    # Strip trailing punctuation first (? / ؟ / . / !)
    text = re.sub(r"[\?؟\.!]+$", "", original).strip()

    # Match and remove leading question pattern
    for pattern in _COMPILED_PREFIXES:
        match = pattern.search(text)
        if match:
            remainder = text[match.end():].strip()
            if remainder:
                return remainder

    return text or original


def build_ts_query(query: str, strategy: FTSStrategy) -> Any:
    """
    Constructs the SQLAlchemy function expression for the PostgreSQL tsquery
    corresponding to the specified experimental strategy.

    Always uses the "simple" dictionary configuration and parameterized queries.
    Never uses raw string interpolation or to_tsquery.
    """
    if strategy == FTSStrategy.BASELINE:
        return func.plainto_tsquery("simple", query)
    elif strategy == FTSStrategy.STOPWORD_STRIPPED:
        stripped = strip_question_tokens(query)
        return func.plainto_tsquery("simple", stripped)
    elif strategy == FTSStrategy.WEBSEARCH_NORMALIZED:
        stripped = strip_question_tokens(query)
        return func.websearch_to_tsquery("simple", stripped)
    elif strategy == FTSStrategy.WEBSEARCH_RAW:
        return func.websearch_to_tsquery("simple", query)
    else:
        raise ValueError(f"Unsupported FTSStrategy: {strategy}")
