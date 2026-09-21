"""
AI-1 Evaluation Schemas — Machine-readable structures for Qwen3:8B baseline evaluation.

Defines schemas for:
- Evaluation documents & conversation turns
- Evaluation test cases with deterministic specifications
- Deterministic check results
- Structured 0-3 rubric scores
- Inference performance metrics
- Case evaluation results and aggregate benchmark summaries
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvalDoc(BaseModel):
    """An isolated evaluation context document or chunk."""
    doc_id: str
    title: str
    text: str


class Turn(BaseModel):
    """A conversational turn in multi-turn history."""
    role: str = "user"  # "user" or "assistant"
    content: str


class DeterministicSpec(BaseModel):
    """Specification of strict, deterministic assertions."""
    required_entities: List[str] = Field(default_factory=list)
    forbidden_terms: List[str] = Field(default_factory=list)
    expected_language: Optional[str] = None  # "en" or "ar"
    expected_refusal: bool = False
    min_citations: int = 0
    valid_source_ids: List[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    """A single evaluation case for Controlled Generation Evaluation."""
    case_id: str
    suite: str  # "smoke" or "baseline"
    category: str  # "english", "arabic", "bilingual", "grounded", "unanswerable", "adversarial"
    language: str  # "en", "ar", "mixed"
    user_query: str
    context_documents: List[EvalDoc] = Field(default_factory=list)
    conversation_history: List[Turn] = Field(default_factory=list)
    expected_behavior: str
    reference_answer: str
    deterministic_checks: DeterministicSpec = Field(default_factory=DeterministicSpec)
    rubric_criteria: List[str] = Field(default_factory=list)
    difficulty: str = "medium"  # "easy", "medium", "hard"


class DeterministicResult(BaseModel):
    """Outcome of automated deterministic checks."""
    passed: bool
    checks: Dict[str, bool] = Field(default_factory=dict)
    failure_reasons: List[str] = Field(default_factory=list)
    citations_extracted: List[str] = Field(default_factory=list)
    refusal_detected: bool = False
    exact_refusal_wording: bool = False
    language_detected: str = "unknown"
    entities_found: List[str] = Field(default_factory=list)
    entities_missing: List[str] = Field(default_factory=list)
    forbidden_terms_found: List[str] = Field(default_factory=list)


class RubricScores(BaseModel):
    """Structured 0–3 human-review or rule-calibrated rubric scores."""
    semantic_correctness: Optional[int] = None      # 0 to 3
    groundedness: Optional[int] = None              # 0 to 3
    instruction_following: Optional[int] = None     # 0 to 3
    arabic_fluency: Optional[int] = None            # 0 to 3
    english_fluency: Optional[int] = None           # 0 to 3
    cross_lingual_quality: Optional[int] = None     # 0 to 3
    semantic_citation_support: Optional[int] = None # 0 to 3
    notes: Dict[str, str] = Field(default_factory=dict)


class PerformanceMetrics(BaseModel):
    """Inference timing and throughput metrics captured during execution."""
    latency_seconds: float = 0.0
    ttft_seconds: Optional[float] = None
    generation_duration_seconds: float = 0.0
    token_count: int = 0
    tokens_per_second: float = 0.0
    prompt_tokens_est: int = 0
    prompt_chars: int = 0


class EvalCaseResult(BaseModel):
    """Complete evaluation record for a single evaluation case."""
    case_id: str
    suite: str
    category: str
    language: str
    model: str = "qwen3:8b"
    user_query: str
    generated_answer: str
    deterministic: DeterministicResult
    rubric: RubricScores
    performance: PerformanceMetrics
    pass_fail: bool
    failure_category: Optional[str] = None  # e.g., "generation correctness", "hallucination", etc.


class BenchmarkSummary(BaseModel):
    """Aggregate benchmark results across all evaluated cases."""
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    pass_rate: float = 0.0
    category_metrics: Dict[str, Any] = Field(default_factory=dict)
    performance_stats: Dict[str, Any] = Field(default_factory=dict)
    failure_breakdown: Dict[str, int] = Field(default_factory=dict)
    results: List[EvalCaseResult] = Field(default_factory=list)
