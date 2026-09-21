"""
CLI Execution Script for AI-2: Qwen3:8B Model Quality Evaluation.

Usage:
  # Fast dry-run / mock verification (instant, default safe mode):
  python scripts/run_ai2_evaluation.py

  # Explicit mock verification with limited cases:
  python scripts/run_ai2_evaluation.py --mock --max-cases 10

  # Live Qwen3:8B quality evaluation (60 cases):
  # NOTE: REQUIRES AUTHORIZATION BEFORE RUNNING LIVE
  python scripts/run_ai2_evaluation.py --live --output ai2_live_results.json
"""

import argparse
import json
import logging
import os
import sys

# Ensure UTF-8 output encoding on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.evaluation.runner import EvaluationRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_ai2_evaluation")


def print_scorecard(summary):
    print("\n" + "=" * 80)
    print("AI-2 MODEL QUALITY EVALUATION SCORECARD (Qwen3:8B)")
    meta = summary.run_metadata
    print(f"Phase: {meta.get('evaluation_phase', 'AI-2 Evaluation')}")
    print(f"Model: {meta.get('model')}  |  Suite: {meta.get('suite', 'ai2').upper()}  |  Live: {meta.get('live_mode')}")
    print(f"Timestamp: {meta.get('timestamp')}")
    print(f"Environment: {meta.get('environment')}")
    print("=" * 80)

    print("\n--- CATEGORY RESULTS ---")
    print(f"{'Category':<28} | {'Total':<6} | {'Passed':<6} | {'Pass Rate':<10} | {'Avg Correct*':<13} | {'Avg Ground*':<13}")
    print("-" * 86)
    for cat, m in summary.category_metrics.items():
        cat_display = cat.replace("_", " ").title()
        print(f"{cat_display:<28} | {m['total']:<6} | {m['passed']:<6} | {m['pass_rate']}%{'':<5} | {m['avg_correctness']:<13} | {m['avg_groundedness']:<13}")
    print("-" * 86)
    print(f"{'OVERALL TOTAL':<28} | {summary.total_cases:<6} | {summary.passed_cases:<6} | {summary.pass_rate}%")
    print("* Note: Rubric scores (Correctness & Groundedness) are rule-calibrated heuristic proxies (0–3), not human judgments.")

    print("\n--- PERFORMANCE STATISTICS (Informational Only) ---")
    p = summary.performance_stats
    print(f"Median Latency:              {p.get('median_latency_s')} s")
    print(f"P95 Latency:                 {p.get('p95_latency_s')} s")
    print(f"Min / Max Latency:           {p.get('min_latency_s')} s / {p.get('max_latency_s')} s")
    print(f"Median TTFT:                 {p.get('median_ttft_s')} s")
    print(f"Median Words/Sec (Proxy):    {p.get('median_tokens_per_sec')} w/s (informational word-count proxy, not BPE tokens)")

    if summary.failure_breakdown:
        print("\n--- FAILURE TAXONOMY BREAKDOWN ---")
        for cat, cnt in summary.failure_breakdown.items():
            print(f"  • {cat:<32}: {cnt} cases")
    else:
        print("\n--- FAILURE TAXONOMY BREAKDOWN ---")
        print("  • Zero failures observed.")

    # Human Review Flags
    human_cases = meta.get("human_review_cases", [])
    print(f"\n--- HUMAN REVIEW RECOMMENDATIONS ({len(human_cases)} cases flagged) ---")
    if human_cases:
        for item in human_cases[:15]:
            reasons_str = "; ".join(item.get("reasons", []))
            print(f"  • [{item['case_id']}] ({item['category']}): {reasons_str}")
        if len(human_cases) > 15:
            print(f"  ... and {len(human_cases) - 15} additional cases (see full JSON output)")
    else:
        print("  • No cases flagged for mandatory human review.")

    print("\n" + "=" * 80)
    print("METHODOLOGICAL NOTICE:")
    print("Automated rubric scores and word-overlap groundedness metrics are heuristic proxies.")
    print("They provide automated consistency checks and regression gates, not human-equivalent")
    print("linguistic judgment or scientifically validated semantic ground truth.")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="AI-2 Model Quality Evaluation Runner")
    parser.add_argument("--live", action="store_true", help="Execute live against Ollama (otherwise runs safe mock/dry-run)")
    parser.add_argument("--mock", action="store_true", help="Explicitly enforce mock execution (default)")
    parser.add_argument("--max-cases", type=int, default=None, help="Limit number of cases evaluated")
    parser.add_argument("--output", type=str, default=None, help="Path to write JSON results")

    args = parser.parse_args()

    # Safe default: live is only enabled if explicitly requested and mock is not forced
    is_live = args.live and not args.mock

    runner = EvaluationRunner(suite="ai2", live=is_live)
    summary = runner.run(max_cases=args.max_cases)

    print_scorecard(summary)

    output_path = args.output
    if not output_path:
        output_path = "ai2_baseline_live_results.json" if is_live else "ai2_mock_results.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info(f"Complete machine-readable AI-2 results saved to: {output_path}")


if __name__ == "__main__":
    main()
