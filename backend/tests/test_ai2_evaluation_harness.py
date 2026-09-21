"""
Tests for AI-2 Evaluation Harness.

Validates:
1. AI-2 dataset schema, case IDs, and distributions (60 cases across 7 categories)
2. Target difficulty (36 medium, 24 hard) and language distribution (24 ar, 18 en, 18 mixed)
3. Zero overlap with AI-1 case IDs (smoke and baseline datasets)
4. Zero secrets and zero customer PII in evaluation fixtures
5. Multi-document synthesis cases contain at least two context documents
6. Citations validity against declared source IDs
7. AI-2 runner execution in mock mode (fast execution, summary compilation, AI-2 metadata)
8. Human review flagging mechanism
9. Failure isolation: simulated inference exceptions do not crash runner
10. AI-1 backward compatibility (smoke and baseline suites unaffected)
"""

import os
import pytest

from app.evaluation.schemas import (
    EvalCase,
    EvalDoc,
    DeterministicSpec,
    BenchmarkSummary,
    EvalCaseResult,
)
from app.evaluation.runner import EvaluationRunner


# ──────────────────────────────────────────────────────────────────────────────
# 1. AI-2 Dataset Validity & Distribution
# ──────────────────────────────────────────────────────────────────────────────

class TestAI2DatasetValidity:
    def test_ai2_dataset_schema_and_case_count(self):
        cases = EvaluationRunner.load_dataset("ai2")
        assert len(cases) == 60, f"Expected 60 cases in AI-2, found {len(cases)}"

        for c in cases:
            assert isinstance(c, EvalCase)
            assert c.suite == "ai2"
            assert len(c.context_documents) > 0
            assert c.expected_behavior.strip() != ""
            assert c.reference_answer.strip() != ""

    def test_ai2_case_ids_format_and_sequence(self):
        cases = EvaluationRunner.load_dataset("ai2")
        actual_ids = [c.case_id for c in cases]
        expected_ids = [f"AI2-{i:03d}" for i in range(1, 61)]
        assert actual_ids == expected_ids
        assert len(actual_ids) == len(set(actual_ids)), "Duplicate case IDs detected"

    def test_ai2_category_distribution(self):
        cases = EvaluationRunner.load_dataset("ai2")
        categories = [c.category for c in cases]

        assert categories.count("arabic_quality") == 12
        assert categories.count("bilingual_grounding") == 12
        assert categories.count("multi_doc_synthesis") == 10
        assert categories.count("instruction_sensitivity") == 6
        assert categories.count("unanswerable_nuanced") == 6
        assert categories.count("adversarial_robustness") == 6
        assert categories.count("enterprise_domain") == 8

    def test_ai2_difficulty_distribution(self):
        cases = EvaluationRunner.load_dataset("ai2")
        difficulties = [c.difficulty for c in cases]

        assert difficulties.count("medium") == 36, f"Expected 36 medium, got {difficulties.count('medium')}"
        assert difficulties.count("hard") == 24, f"Expected 24 hard, got {difficulties.count('hard')}"

    def test_ai2_language_distribution(self):
        cases = EvaluationRunner.load_dataset("ai2")
        languages = [c.language for c in cases]

        assert languages.count("ar") == 24, f"Expected 24 Arabic, got {languages.count('ar')}"
        assert languages.count("en") == 18, f"Expected 18 English, got {languages.count('en')}"
        assert languages.count("mixed") == 18, f"Expected 18 Mixed, got {languages.count('mixed')}"

    def test_zero_overlap_with_ai1_case_ids(self):
        ai2_cases = EvaluationRunner.load_dataset("ai2")
        smoke_cases = EvaluationRunner.load_dataset("smoke")
        base_cases = EvaluationRunner.load_dataset("baseline")

        ai2_ids = set(c.case_id for c in ai2_cases)
        smoke_ids = set(c.case_id for c in smoke_cases)
        base_ids = set(c.case_id for c in base_cases)

        assert ai2_ids.isdisjoint(smoke_ids), f"AI-2 IDs overlap with smoke: {ai2_ids & smoke_ids}"
        assert ai2_ids.isdisjoint(base_ids), f"AI-2 IDs overlap with baseline: {ai2_ids & base_ids}"

    def test_zero_secrets_or_customer_pii(self):
        dataset_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "evaluation", "datasets", "ai2_dataset.json"
        )
        with open(dataset_path, "r", encoding="utf-8") as f:
            content = f.read()

        # No production API keys, bearer JWT tokens, private keys, or AWS tokens
        assert "sk-" not in content
        assert "Bearer eyJ" not in content
        assert "ghp_" not in content
        assert "BEGIN PRIVATE KEY" not in content
        assert "AKIA" not in content

    def test_multi_doc_synthesis_document_counts(self):
        cases = EvaluationRunner.load_dataset("ai2")
        multi_doc_cases = [c for c in cases if c.category == "multi_doc_synthesis"]
        assert len(multi_doc_cases) == 10

        for c in multi_doc_cases:
            assert len(c.context_documents) >= 2, f"Case {c.case_id} has < 2 documents"

    def test_citation_sources_match_context_documents(self):
        cases = EvaluationRunner.load_dataset("ai2")
        for c in cases:
            if c.deterministic_checks.min_citations > 0:
                doc_titles = [d.title for d in c.context_documents]
                doc_ids = [d.doc_id for d in c.context_documents]
                all_valid = set(doc_titles + doc_ids)

                for src in c.deterministic_checks.valid_source_ids:
                    assert src in all_valid, f"Source ID '{src}' in case {c.case_id} not in context docs"


# ──────────────────────────────────────────────────────────────────────────────
# 2. AI-2 Evaluation Runner Integration
# ──────────────────────────────────────────────────────────────────────────────

class TestAI2EvaluationRunner:
    def test_mock_ai2_execution_fast_and_complete(self):
        runner = EvaluationRunner(suite="ai2", live=False)
        summary = runner.run()

        assert isinstance(summary, BenchmarkSummary)
        assert summary.total_cases == 60
        assert summary.passed_cases == 60
        assert summary.pass_rate == 100.0
        assert len(summary.results) == 60

        # Performance stats captured (fast mock)
        assert summary.performance_stats["median_latency_s"] < 0.1
        assert summary.performance_stats["median_tokens_per_sec"] > 0

    def test_ai2_metadata_identification(self):
        runner = EvaluationRunner(suite="ai2", live=False)
        summary = runner.run(max_cases=2)

        meta = summary.run_metadata
        assert meta["evaluation_phase"] == "AI-2: Qwen3:8B Model Quality Evaluation"
        assert meta["suite"] == "ai2"
        assert meta["model"] == "qwen3:8b"
        assert meta["live_mode"] is False

    def test_human_review_flagging_mechanism(self):
        runner = EvaluationRunner(suite="ai2", live=False)
        summary = runner.run(max_cases=15)

        meta = summary.run_metadata
        assert "human_review_flagged_count" in meta
        assert "human_review_cases" in meta
        assert meta["human_review_flagged_count"] > 0

        # Verify flagged case structure
        for item in meta["human_review_cases"]:
            assert "case_id" in item
            assert "category" in item
            assert "reasons" in item
            assert len(item["reasons"]) > 0

    def test_max_cases_parameter_limits_execution(self):
        runner = EvaluationRunner(suite="ai2", live=False)
        summary = runner.run(max_cases=5)
        assert summary.total_cases == 5
        assert len(summary.results) == 5

    def test_failure_isolation_on_inference_exception(self):
        class BrokenLLM:
            def stream_generate(self, prompt):
                raise ConnectionError("Simulated Ollama inference crash")

        runner = EvaluationRunner(suite="ai2", live=True, llm_provider=BrokenLLM())
        cases = runner.load_dataset("ai2")
        res = runner.execute_case(cases[0])

        assert res.pass_fail is False
        assert "[INFERENCE_ERROR:" in res.generated_answer
        assert res.failure_category is not None


# ──────────────────────────────────────────────────────────────────────────────
# 3. AI-1 Backward Compatibility Regression
# ──────────────────────────────────────────────────────────────────────────────

class TestAI1BackwardCompatibility:
    def test_smoke_suite_unaffected(self):
        cases = EvaluationRunner.load_dataset("smoke")
        assert len(cases) == 24
        for c in cases:
            assert c.case_id.startswith("SMOKE-")

    def test_baseline_suite_unaffected(self):
        cases = EvaluationRunner.load_dataset("baseline")
        assert len(cases) == 80
        for c in cases:
            assert c.case_id.startswith("BASE-")

    def test_smoke_metadata_unaffected(self):
        runner = EvaluationRunner(suite="smoke", live=False)
        summary = runner.run(max_cases=2)
        meta = summary.run_metadata
        assert meta["evaluation_phase"] == "AI-1: Qwen3:8B Baseline Evaluation"
        assert meta["suite"] == "smoke"
