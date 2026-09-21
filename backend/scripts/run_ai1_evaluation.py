"""
CLI Execution Script for AI-1: Qwen3:8B Baseline Quality + Performance Evaluation.

Usage:
  # Fast dry-run / mock verification (instant):
  python scripts/run_ai1_evaluation.py --suite smoke

  # Live Qwen3:8B smoke benchmark (24 cases):
  python scripts/run_ai1_evaluation.py --suite smoke --live --output smoke_results.json

  # Live Qwen3:8B full baseline benchmark (80 cases):
  python scripts/run_ai1_evaluation.py --suite baseline --live --output baseline_results.json
"""

import argparse
import json
import logging
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.evaluation.runner import EvaluationRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_ai1_evaluation")


def print_scorecard(summary):
    print("\n" + "=" * 80)
    print("AI-1 CONTROLLED GENERATION EVALUATION SCORECARD")
    print(f"Model: {summary.run_metadata.get('model')}  |  Suite: {summary.run_metadata.get('suite').upper()}  |  Live: {summary.run_metadata.get('live_mode')}")
    print(f"Timestamp: {summary.run_metadata.get('timestamp')}")
    print(f"Environment: {summary.run_metadata.get('environment')}")
    print("=" * 80)

    print("\n--- CATEGORY RESULTS ---")
    print(f"{'Category':<25} | {'Total':<6} | {'Passed':<6} | {'Pass Rate':<10} | {'Avg Correct':<12} | {'Avg Grounded':<12}")
    print("-" * 80)
    for cat, m in summary.category_metrics.items():
        print(f"{cat.capitalize():<25} | {m['total']:<6} | {m['passed']:<6} | {m['pass_rate']}%{'':<5} | {m['avg_correctness']:<12} | {m['avg_groundedness']:<12}")
    print("-" * 80)
    print(f"{'OVERALL TOTAL':<25} | {summary.total_cases:<6} | {summary.passed_cases:<6} | {summary.pass_rate}%")

    print("\n--- PERFORMANCE STATISTICS (Ryzen 7 CPU Inference) ---")
    p = summary.performance_stats
    print(f"Median Latency:       {p.get('median_latency_s')} s")
    print(f"P95 Latency:          {p.get('p95_latency_s')} s")
    print(f"Min / Max Latency:    {p.get('min_latency_s')} s / {p.get('max_latency_s')} s")
    print(f"Median TTFT:          {p.get('median_ttft_s')} s")
    print(f"Median Tokens/Sec:    {p.get('median_tokens_per_sec')} t/s")

    if summary.failure_breakdown:
        print("\n--- FAILURE TAXONOMY BREAKDOWN ---")
        for cat, cnt in summary.failure_breakdown.items():
            print(f"  • {cat:<32}: {cnt} cases")
    else:
        print("\n--- FAILURE TAXONOMY BREAKDOWN ---")
        print("  • Zero failures observed.")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="AI-1 Baseline Evaluation Runner")
    parser.add_argument("--suite", choices=["smoke", "baseline"], default="smoke", help="Evaluation suite (smoke=24, baseline=80)")
    parser.add_argument("--live", action="store_true", help="Execute live against Ollama (otherwise runs mock/dry-run)")
    parser.add_argument("--max-cases", type=int, default=None, help="Limit number of cases evaluated")
    parser.add_argument("--output", type=str, default=None, help="Path to write JSON results")

    args = parser.parse_args()

    runner = EvaluationRunner(suite=args.suite, live=args.live)
    summary = runner.run(max_cases=args.max_cases)

    print_scorecard(summary)

    output_path = args.output
    if not output_path:
        output_path = f"ai1_{args.suite}_{'live' if args.live else 'mock'}_results.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info(f"Complete machine-readable results saved to: {output_path}")


if __name__ == "__main__":
    main()
