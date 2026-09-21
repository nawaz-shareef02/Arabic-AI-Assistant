"""
AI-1 Evaluation Runner — Sequential Controlled Generation Execution Engine.

Executes evaluation cases sequentially against Qwen3:8B via OllamaProvider,
capturing latency, TTFT, token throughput, deterministic check outcomes,
and structured 0–3 rubric scores.

Supports:
- Live inference execution via OllamaProvider
- Dry-run / mock execution for fast CI testing
- Structured JSON output persistence
- Comprehensive summary scorecard generation
"""

import json
import logging
import os
import time
import numpy as np
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.evaluation.schemas import (
    BenchmarkSummary,
    DeterministicResult,
    EvalCase,
    EvalCaseResult,
    PerformanceMetrics,
    RubricScores,
    Turn,
)
from app.evaluation.deterministic_evaluator import DeterministicEvaluator
from app.evaluation.rubric_evaluator import RubricEvaluator
from app.services.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class EvaluationRunner:
    """Orchestrates sequential controlled generation benchmark runs."""

    def __init__(
        self,
        suite: str = "smoke",
        live: bool = False,
        llm_provider=None,
    ):
        self.suite = suite
        self.live = live
        self._llm = llm_provider

        if self.live and self._llm is None:
            from app.services.llm.ollama_provider import OllamaProvider
            self._llm = OllamaProvider.get_instance()

    @classmethod
    def load_dataset(cls, suite: str = "smoke") -> List[EvalCase]:
        """Loads evaluation cases from version-controlled JSON datasets."""
        base_dir = os.path.dirname(__file__)
        if suite == "smoke":
            filename = "smoke_dataset.json"
        elif suite == "ai2":
            filename = "ai2_dataset.json"
        else:
            filename = "baseline_dataset.json"
        path = os.path.join(base_dir, "datasets", filename)

        if not os.path.exists(path):
            raise FileNotFoundError(f"Dataset file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        return [EvalCase(**item) for item in raw]

    def build_prompt_for_case(self, case: EvalCase) -> str:
        """Constructs grounded prompt using production PromptBuilder."""
        contexts = [doc.text for doc in case.context_documents]
        if case.conversation_history:
            return PromptBuilder.build_conversation_prompt(
                question=case.user_query,
                contexts=contexts,
                history=case.conversation_history,
            )
        return PromptBuilder.build_prompt(
            question=case.user_query,
            contexts=contexts,
        )

    def warmup(self) -> None:
        """Runs a single 1-token generation to ensure model is resident in RAM."""
        if self.live and self._llm is not None:
            try:
                logger.info("Executing benchmark warmup cycle...")
                self._llm.generate("warmup", max_tokens=1)
            except Exception as ex:
                logger.warning(f"Warmup cycle failed or skipped: {ex}")

    def execute_case(self, case: EvalCase) -> EvalCaseResult:
        """Executes a single evaluation case and scores the output."""
        prompt = self.build_prompt_for_case(case)
        prompt_chars = len(prompt)
        prompt_tokens_est = int(prompt_chars / 4)

        perf = PerformanceMetrics(
            prompt_chars=prompt_chars,
            prompt_tokens_est=prompt_tokens_est,
        )

        t0 = time.perf_counter()

        if self.live and self._llm is not None:
            # Sequential live execution via OllamaProvider
            first_token_time: Optional[float] = None
            chunks: List[str] = []

            try:
                for token in self._llm.stream_generate(prompt):
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    chunks.append(token)

                generated_answer = "".join(chunks).strip()
                t1 = time.perf_counter()

                perf.latency_seconds = round(t1 - t0, 3)
                perf.generation_duration_seconds = perf.latency_seconds
                if first_token_time is not None:
                    perf.ttft_seconds = round(first_token_time - t0, 3)
                perf.token_count = len(generated_answer.split())
                if perf.latency_seconds > 0:
                    perf.tokens_per_second = round(perf.token_count / perf.latency_seconds, 2)

            except Exception as ex:
                t1 = time.perf_counter()
                perf.latency_seconds = round(t1 - t0, 3)
                logger.error(f"Inference error on case {case.case_id}: {ex}")
                generated_answer = f"[INFERENCE_ERROR: {ex}]"
        else:
            # Mock execution: returns reference answer for deterministic harness testing
            time.sleep(0.005)  # simulate minimal processing
            t1 = time.perf_counter()
            generated_answer = case.reference_answer
            perf.latency_seconds = round(t1 - t0, 3)
            perf.ttft_seconds = 0.001
            perf.generation_duration_seconds = perf.latency_seconds
            perf.token_count = len(generated_answer.split())
            perf.tokens_per_second = 100.0

        # Run Deterministic evaluation
        det_result = DeterministicEvaluator.evaluate(case, generated_answer)

        # Run Structured 0-3 Rubric evaluation
        rubric_result = RubricEvaluator.score_case(case, generated_answer, det_result)

        # Failure classification
        failure_cat = None
        if not det_result.passed or (rubric_result.semantic_correctness is not None and rubric_result.semantic_correctness < 2):
            failure_cat = RubricEvaluator.classify_failure(case, det_result, rubric_result)

        pass_fail = (failure_cat is None) and det_result.passed

        return EvalCaseResult(
            case_id=case.case_id,
            suite=case.suite,
            category=case.category,
            language=case.language,
            model="qwen3:8b",
            user_query=case.user_query,
            generated_answer=generated_answer,
            deterministic=det_result,
            rubric=rubric_result,
            performance=perf,
            pass_fail=pass_fail,
            failure_category=failure_cat,
        )

    def run(self, max_cases: Optional[int] = None) -> BenchmarkSummary:
        """Executes the suite sequentially and compiles the aggregate summary."""
        cases = self.load_dataset(self.suite)
        if max_cases:
            cases = cases[:max_cases]

        phase_label = "AI-2" if self.suite == "ai2" else "AI-1"
        logger.info(f"Starting {phase_label} Evaluation | Suite: {self.suite} | Mode: {'LIVE' if self.live else 'MOCK'} | Total cases: {len(cases)}")

        self.warmup()

        results: List[EvalCaseResult] = []
        for idx, case in enumerate(cases, start=1):
            logger.info(f"Evaluating [{idx}/{len(cases)}] {case.case_id} ({case.category})...")
            res = self.execute_case(case)
            results.append(res)

        return self.compile_summary(results)

    def compile_summary(self, results: List[EvalCaseResult]) -> BenchmarkSummary:
        """Compiles machine-readable statistics, scorecards, and performance metrics."""
        total = len(results)
        passed = sum(1 for r in results if r.pass_fail)
        failed = total - passed
        pass_rate = round((passed / total * 100.0), 2) if total > 0 else 0.0

        # Performance percentiles
        latencies = [r.performance.latency_seconds for r in results if r.performance.latency_seconds > 0]
        ttfts = [r.performance.ttft_seconds for r in results if r.performance.ttft_seconds is not None]
        tps_list = [r.performance.tokens_per_second for r in results if r.performance.tokens_per_second > 0]

        perf_stats = {
            "median_latency_s": round(float(np.median(latencies)), 3) if latencies else 0.0,
            "p95_latency_s": round(float(np.percentile(latencies, 95)), 3) if latencies else 0.0,
            "min_latency_s": round(float(np.min(latencies)), 3) if latencies else 0.0,
            "max_latency_s": round(float(np.max(latencies)), 3) if latencies else 0.0,
            "median_ttft_s": round(float(np.median(ttfts)), 3) if ttfts else 0.0,
            "median_tokens_per_sec": round(float(np.median(tps_list)), 2) if tps_list else 0.0,
        }

        # Category metrics breakdown
        cat_metrics: Dict[str, Any] = {}
        for r in results:
            cat = r.category
            if cat not in cat_metrics:
                cat_metrics[cat] = {
                    "total": 0,
                    "passed": 0,
                    "correctness_scores": [],
                    "groundedness_scores": [],
                }
            cat_metrics[cat]["total"] += 1
            if r.pass_fail:
                cat_metrics[cat]["passed"] += 1
            if r.rubric.semantic_correctness is not None:
                cat_metrics[cat]["correctness_scores"].append(r.rubric.semantic_correctness)
            if r.rubric.groundedness is not None:
                cat_metrics[cat]["groundedness_scores"].append(r.rubric.groundedness)

        for cat, data in cat_metrics.items():
            tot = data["total"]
            data["pass_rate"] = round(data["passed"] / tot * 100.0, 1) if tot > 0 else 0.0
            data["avg_correctness"] = round(float(np.mean(data["correctness_scores"])), 2) if data["correctness_scores"] else 0.0
            data["avg_groundedness"] = round(float(np.mean(data["groundedness_scores"])), 2) if data["groundedness_scores"] else 0.0
            del data["correctness_scores"]
            del data["groundedness_scores"]

        # Failure breakdown
        failure_counts: Dict[str, int] = {}
        for r in results:
            if r.failure_category:
                failure_counts[r.failure_category] = failure_counts.get(r.failure_category, 0) + 1

        # Identify cases flagged for human review
        human_review_cases = []
        for r in results:
            reasons = []
            if r.category in ("arabic_quality", "bilingual_grounding", "enterprise_domain"):
                reasons.append(f"{r.category.replace('_', ' ').title()} review")
            if r.rubric.groundedness is not None and r.rubric.groundedness <= 1:
                reasons.append("Low groundedness proxy (score <= 1)")
            if r.failure_category == "hallucination":
                reasons.append("Suspected hallucination")
            if r.deterministic.forbidden_terms_found:
                reasons.append(f"Forbidden terms / injection leakage: {r.deterministic.forbidden_terms_found}")
            if r.category == "unanswerable_nuanced":
                if not r.deterministic.refusal_detected:
                    reasons.append("Nuanced refusal failure")
                else:
                    reasons.append("Nuanced refusal verification")
            if reasons:
                human_review_cases.append({
                    "case_id": r.case_id,
                    "category": r.category,
                    "reasons": reasons,
                })

        phase_title = "AI-2: Qwen3:8B Model Quality Evaluation" if self.suite == "ai2" else "AI-1: Qwen3:8B Baseline Evaluation"

        run_metadata = {
            "evaluation_phase": phase_title,
            "model": "qwen3:8b",
            "evaluation_type": "Controlled Generation Evaluation",
            "suite": self.suite,
            "live_mode": self.live,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": "AMD Ryzen 7 5700U (CPU inference, 31.3 GB RAM)",
            "ollama_options": {
                "think": False,
                "keep_alive": "24h",
                "max_concurrency": 1,
                "acquire_timeout": 0.0,
            },
            "human_review_flagged_count": len(human_review_cases),
            "human_review_cases": human_review_cases,
        }

        return BenchmarkSummary(
            run_metadata=run_metadata,
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            pass_rate=pass_rate,
            category_metrics=cat_metrics,
            performance_stats=perf_stats,
            failure_breakdown=failure_counts,
            results=results,
        )
