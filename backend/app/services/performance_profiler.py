"""
PerformanceProfiler — Refinement #5: RAG Stage Bottleneck Analysis.

Captures breakdown timings and automatically identifies the slowest sub-stage
(e.g., Vector Search: 52% of Total Latency) as an optimization candidate.
"""

from typing import Dict, Any


class PerformanceProfiler:
    @staticmethod
    def analyze_bottlenecks(stage_timings_ms: Dict[str, float]) -> Dict[str, Any]:
        """
        Refinement #5: Identifies latency bottlenecks across RAG sub-stages.
        """
        total_ms = sum(stage_timings_ms.values()) or 1.0
        percentages = {stage: round((dur / total_ms) * 100, 1) for stage, dur in stage_timings_ms.items()}

        # Find slowest stage
        slowest_stage = max(stage_timings_ms, key=stage_timings_ms.get) if stage_timings_ms else "Unknown"
        slowest_pct = percentages.get(slowest_stage, 0.0)

        return {
            "total_latency_ms": round(total_ms, 2),
            "stage_breakdown_ms": stage_timings_ms,
            "stage_percentage": percentages,
            "bottleneck_stage": slowest_stage,
            "bottleneck_percentage": slowest_pct,
            "recommendation": f"Optimize '{slowest_stage}' which accounts for {slowest_pct}% of total RAG latency.",
        }
