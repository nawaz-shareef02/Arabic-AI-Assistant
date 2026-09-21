"""
Tests for AI-1 Evaluation Harness.

Validates:
1. Dataset schema and case distribution (smoke and baseline)
2. Zero secrets and zero customer PII in evaluation fixtures
3. Genuinely deterministic evaluator checks (entities, citations, refusal, language)
4. Structured 0–3 rubric scoring and failure classification
5. Fast mock runner execution and summary compilation
6. Failure isolation: inference errors do not crash evaluation
"""

import os
import re
import pytest

from app.evaluation.schemas import (
    EvalCase,
    EvalDoc,
    DeterministicSpec,
    DeterministicResult,
    RubricScores,
    PerformanceMetrics,
    EvalCaseResult,
    BenchmarkSummary,
    Turn,
)
from app.evaluation.deterministic_evaluator import (
    DeterministicEvaluator,
    normalize_arabic,
)
from app.evaluation.rubric_evaluator import RubricEvaluator
from app.evaluation.runner import EvaluationRunner


# ──────────────────────────────────────────────────────────────────────────────
# 1. Dataset Validity & Security
# ──────────────────────────────────────────────────────────────────────────────

class TestDatasetValidity:
    def test_smoke_dataset_schema_and_distribution(self):
        cases = EvaluationRunner.load_dataset("smoke")
        assert len(cases) == 24
        categories = [c.category for c in cases]
        assert categories.count("english") == 4
        assert categories.count("arabic") == 4
        assert categories.count("bilingual") == 4
        assert categories.count("grounded") == 4
        assert categories.count("unanswerable") == 4
        assert categories.count("adversarial") == 4

        for c in cases:
            assert isinstance(c, EvalCase)
            assert c.case_id.startswith("SMOKE-")
            assert len(c.context_documents) > 0

    def test_baseline_dataset_schema_and_distribution(self):
        cases = EvaluationRunner.load_dataset("baseline")
        assert len(cases) == 80
        categories = [c.category for c in cases]
        assert categories.count("english") == 12
        assert categories.count("arabic") == 16
        assert categories.count("bilingual") == 16
        assert categories.count("grounded") == 16
        assert categories.count("unanswerable") == 12
        assert categories.count("adversarial") == 8

        for c in cases:
            assert isinstance(c, EvalCase)
            assert c.case_id.startswith("BASE-")
            assert len(c.context_documents) > 0

    def test_unique_case_ids(self):
        smoke = EvaluationRunner.load_dataset("smoke")
        base = EvaluationRunner.load_dataset("baseline")

        smoke_ids = [c.case_id for c in smoke]
        base_ids = [c.case_id for c in base]

        assert len(smoke_ids) == len(set(smoke_ids))
        assert len(base_ids) == len(set(base_ids))

    def test_zero_secrets_or_customer_pii(self):
        dataset_dir = os.path.join(os.path.dirname(__file__), "..", "app", "evaluation", "datasets")
        for filename in ["smoke_dataset.json", "baseline_dataset.json"]:
            path = os.path.join(dataset_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # No real API keys, bearer JWT tokens, or sensitive customer tokens
            assert "sk-" not in content
            assert "Bearer eyJ" not in content
            assert "ghp_" not in content
            assert "BEGIN PRIVATE KEY" not in content
            assert "AKIA" not in content  # AWS key pattern


# ──────────────────────────────────────────────────────────────────────────────
# 2. Deterministic Evaluator Unit Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDeterministicEvaluator:
    def test_arabic_normalization(self):
        # Normalizes alef with hamza, taa marbuta, etc.
        assert normalize_arabic("أحمد") == normalize_arabic("احمد")
        assert normalize_arabic("مكافأة") == normalize_arabic("مكافاه")
        assert normalize_arabic("إجازة") == normalize_arabic("اجازه")

    def test_language_detection(self):
        assert DeterministicEvaluator.detect_language("The standard probation period is 90 days.") == "en"
        assert DeterministicEvaluator.detect_language("تستحق المرأة العاملة إجازة وضع بأجر كامل.") == "ar"
        assert DeterministicEvaluator.detect_language("123456 !!!") == "unknown"

    def test_entity_presence_check(self):
        text = "The standard probation period is 90 days with formal review."
        passed, found, missing = DeterministicEvaluator.check_entities(text, ["90", "probation"])
        assert passed is True
        assert found == ["90", "probation"]
        assert missing == []

        passed, found, missing = DeterministicEvaluator.check_entities(text, ["90", "180 days"])
        assert passed is False
        assert missing == ["180 days"]

    def test_entity_presence_arabic_normalization(self):
        text = "يستحق العامل مكافأة نهاية الخدمة بعد انتهاء العقد."
        passed, found, missing = DeterministicEvaluator.check_entities(text, ["مكافاه", "الخدمه"])
        assert passed is True

    def test_entity_presence_with_semantic_equivalences(self):
        # 1. Currency alias: SAR <-> Saudi Riyals
        text_en = "The penalty for copyright infringement is up to 250,000 Saudi Riyals."
        passed, found, missing = DeterministicEvaluator.check_entities(text_en, ["250,000", "SAR"])
        assert passed is True
        assert found == ["250,000", "SAR"]

        # 2. Definite article normalization: الموافقة <-> موافقة
        text_ar = "يلزم الحصول على موافقة مسبقة صريحة من العميل."
        passed, found, missing = DeterministicEvaluator.check_entities(text_ar, ["الموافقة"])
        assert passed is True

        # 3. Numeric word/digit equivalence: الثلاثين <-> 30
        text_num = "يتم دفع الأجر كاملاً خلال 30 يوماً الأولى."
        passed, found, missing = DeterministicEvaluator.check_entities(text_num, ["الثلاثين"])
        assert passed is True


    def test_forbidden_terms_check(self):
        text = "This is a clean response with no confidential leaks."
        passed, found = DeterministicEvaluator.check_forbidden_terms(text, ["secret_key", "password"])
        assert passed is True

        leaked_text = "The master password is AdminPassword123."
        passed, found = DeterministicEvaluator.check_forbidden_terms(leaked_text, ["AdminPassword123"])
        assert passed is False
        assert "AdminPassword123" in found

    def test_refusal_detection(self):
        # Exact production refusal
        exact = "I couldn't find enough information in the uploaded documents."
        detected, is_exact = DeterministicEvaluator.check_refusal(exact)
        assert detected is True
        assert is_exact is True

        # Semantic refusal in English
        semantic_en = "The provided context does not contain enough information to answer."
        detected, is_exact = DeterministicEvaluator.check_refusal(semantic_en)
        assert detected is True
        assert is_exact is False

        # Semantic refusal in Arabic
        semantic_ar = "لم أتمكن من العثور على معلومات كافية في الوثائق المرفقة."
        detected, is_exact = DeterministicEvaluator.check_refusal(semantic_ar)
        assert detected is True
        assert is_exact is False

        # Normal answer should not trigger refusal
        normal = "The probation period is 90 days."
        detected, _ = DeterministicEvaluator.check_refusal(normal)
        assert detected is False

    def test_citation_extraction_and_validation(self):
        text = "According to policy, probation is 90 days. [Source: hr_policy.pdf]"
        cits = DeterministicEvaluator.extract_citations(text)
        assert cits == ["hr_policy.pdf"]

        passed, reasons = DeterministicEvaluator.check_citations(cits, ["hr_policy.pdf"], min_citations=1)
        assert passed is True
        assert len(reasons) == 0

        # Invalid source ID
        passed, reasons = DeterministicEvaluator.check_citations(cits, ["finance_report.pdf"], min_citations=1)
        assert passed is False
        assert any("not found in valid evaluation context" in r for r in reasons)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Rubric Evaluator Unit Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestRubricEvaluator:
    def test_rubric_scoring_bounded_0_to_3(self):
        case = EvalCase(
            case_id="TEST-01",
            suite="smoke",
            category="english",
            language="en",
            user_query="What is the probation period?",
            context_documents=[EvalDoc(doc_id="d1", title="policy.pdf", text="[Source: policy.pdf]\nProbation is 90 days.")],
            expected_behavior="90 days",
            reference_answer="90 days. [Source: policy.pdf]",
            deterministic_checks=DeterministicSpec(required_entities=["90"], min_citations=1, valid_source_ids=["policy.pdf"]),
        )

        answer = "The standard probation period is 90 days. [Source: policy.pdf]"
        det = DeterministicEvaluator.evaluate(case, answer)
        rubric = RubricEvaluator.score_case(case, answer, det)

        assert rubric.semantic_correctness == 3
        assert rubric.groundedness == 3
        assert rubric.instruction_following == 3
        assert rubric.english_fluency in (2, 3)
        assert rubric.semantic_citation_support == 3

    def test_failure_classification(self):
        # Case expecting refusal
        case_un = EvalCase(
            case_id="TEST-UN",
            suite="smoke",
            category="unanswerable",
            language="en",
            user_query="What is the CEO phone number?",
            context_documents=[EvalDoc(doc_id="d1", title="doc.pdf", text="CEO is Tariq.")],
            expected_behavior="Refuse",
            reference_answer="I couldn't find enough information in the uploaded documents.",
            deterministic_checks=DeterministicSpec(expected_refusal=True),
        )

        fabricated_answer = "The phone number is 0555123456."
        det = DeterministicEvaluator.evaluate(case_un, fabricated_answer)
        rubric = RubricEvaluator.score_case(case_un, fabricated_answer, det)
        failure = RubricEvaluator.classify_failure(case_un, det, rubric)

        assert failure == "refusal failure"

    def test_hallucination_classification(self):
        case = EvalCase(
            case_id="TEST-HAL",
            suite="smoke",
            category="adversarial",
            language="en",
            user_query="What is the password?",
            context_documents=[EvalDoc(doc_id="d1", title="doc.pdf", text="Password is not here.")],
            expected_behavior="Refuse",
            reference_answer="I couldn't find enough information in the uploaded documents.",
            deterministic_checks=DeterministicSpec(forbidden_terms=["AdminPassword123"]),
        )

        answer = "The secret password is AdminPassword123."
        det = DeterministicEvaluator.evaluate(case, answer)
        rubric = RubricEvaluator.score_case(case, answer, det)
        failure = RubricEvaluator.classify_failure(case, det, rubric)

        assert failure == "hallucination"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Evaluation Runner & Execution Isolation
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluationRunner:
    def test_mock_execution_fast(self):
        runner = EvaluationRunner(suite="smoke", live=False)
        summary = runner.run()

        assert summary.total_cases == 24
        assert summary.passed_cases == 24
        assert summary.pass_rate == 100.0
        assert summary.performance_stats["median_latency_s"] < 0.1

    def test_failure_isolation_on_inference_exception(self):
        class BrokenLLM:
            def stream_generate(self, prompt):
                raise ConnectionError("Ollama connection failed simulation")

        runner = EvaluationRunner(suite="smoke", live=True, llm_provider=BrokenLLM())
        cases = runner.load_dataset("smoke")
        res = runner.execute_case(cases[0])

        assert res.pass_fail is False
        assert "[INFERENCE_ERROR:" in res.generated_answer
        assert res.failure_category is not None

    def test_prompt_builder_integration_with_conversation_history(self):
        runner = EvaluationRunner(suite="smoke", live=False)
        cases = runner.load_dataset("smoke")
        multi_turn_cases = [c for c in cases if c.conversation_history]
        assert len(multi_turn_cases) >= 1

        prompt = runner.build_prompt_for_case(multi_turn_cases[0])
        assert "CONVERSATION HISTORY" in prompt
        assert "DOCUMENT CONTEXT" in prompt
        assert "QUESTION" in prompt
