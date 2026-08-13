"""
RetrievalProfiler — Structured Pipeline Timing.

Single Responsibility: collect, store, and log per-stage timing metrics
for the entire retrieval pipeline. All timing data is centralized here —
no scattered timing logs across services.

Usage
-----
    profiler = RetrievalProfiler()
    profiler.start("embedding")
    vector = embed(query)
    profiler.stop("embedding")
    ...
    profiler.log_report("streaming")
"""

import time
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RetrievalMetrics:
    """All timing (ms) and count metrics for a single retrieval request."""

    query_expansion_ms: float = 0.0
    embedding_ms: float = 0.0
    dense_search_ms: float = 0.0
    keyword_search_ms: float = 0.0
    fusion_ms: float = 0.0
    filtering_ms: float = 0.0
    rerank_ms: float = 0.0
    prompt_build_ms: float = 0.0
    llm_ms: float = 0.0
    streaming_ms: float = 0.0
    first_token_ms: float = 0.0
    total_ms: float = 0.0

    token_count: int = 0
    dense_results: int = 0
    keyword_results: int = 0
    fused_results: int = 0
    final_results: int = 0


class RetrievalProfiler:
    """
    Context-aware timing profiler for the retrieval pipeline.

    Each stage is timed independently via start()/stop() pairs.
    Counts and custom values are set via set().
    finalize() computes the total wall-clock time.
    log_report() emits a structured ASCII table to the logger.
    """

    def __init__(self) -> None:
        self._metrics = RetrievalMetrics()
        self._timers: dict[str, float] = {}
        self._total_start = time.perf_counter()

    @property
    def metrics(self) -> RetrievalMetrics:
        """Access the current metrics snapshot."""
        return self._metrics

    def start(self, stage: str) -> None:
        """Begin timing a pipeline stage."""
        self._timers[stage] = time.perf_counter()

    def stop(self, stage: str) -> None:
        """
        End timing a pipeline stage and record elapsed milliseconds.

        The stage name must match a ``*_ms`` attribute on RetrievalMetrics
        (e.g. ``start("embedding")`` → sets ``embedding_ms``).
        """
        if stage in self._timers:
            elapsed = (time.perf_counter() - self._timers[stage]) * 1000
            attr = f"{stage}_ms"
            if hasattr(self._metrics, attr):
                setattr(self._metrics, attr, elapsed)
            del self._timers[stage]

    def set(self, key: str, value: object) -> None:
        """Set an arbitrary metric (e.g. result counts)."""
        if hasattr(self._metrics, key):
            setattr(self._metrics, key, value)

    def set_first_token(self) -> None:
        """Record first-token latency relative to pipeline start."""
        self._metrics.first_token_ms = (
            (time.perf_counter() - self._total_start) * 1000
        )

    def finalize(self) -> RetrievalMetrics:
        """Compute total wall-clock time and return final metrics."""
        self._metrics.total_ms = (
            (time.perf_counter() - self._total_start) * 1000
        )
        return self._metrics

    def log_report(self, mode: str = "streaming") -> RetrievalMetrics:
        """Emit a structured timing report and return the metrics."""
        m = self.finalize()
        throughput = (
            (m.token_count / (m.llm_ms / 1000)) if m.llm_ms > 0 else 0
        )

        logger.info(
            "\n"
            "┌───────────────────────────────────────────────┐\n"
            "│    Sprint 12 — Retrieval Pipeline Profiler     │\n"
            f"│    Mode: {mode:<38s}│\n"
            "├───────────────────────────────────────────────┤\n"
            f"│  Query Expansion     : {m.query_expansion_ms:>10.1f} ms      │\n"
            f"│  Embedding           : {m.embedding_ms:>10.1f} ms      │\n"
            f"│  Dense Search        : {m.dense_search_ms:>10.1f} ms      │\n"
            f"│  Keyword Search      : {m.keyword_search_ms:>10.1f} ms      │\n"
            f"│  Rank Fusion (RRF)   : {m.fusion_ms:>10.1f} ms      │\n"
            f"│  Metadata Filter     : {m.filtering_ms:>10.1f} ms      │\n"
            f"│  Re-ranking          : {m.rerank_ms:>10.1f} ms      │\n"
            f"│  Prompt Build        : {m.prompt_build_ms:>10.1f} ms      │\n"
            f"│  LLM / Generation    : {m.llm_ms:>10.1f} ms      │\n"
            f"│  First Token         : {m.first_token_ms:>10.1f} ms      │\n"
            "│  ─────────────────────────────────────────    │\n"
            f"│  Total               : {m.total_ms:>10.1f} ms      │\n"
            f"│  Tokens              : {m.token_count:>10d}         │\n"
            f"│  Throughput          : {throughput:>10.1f} tok/s   │\n"
            f"│  Dense / KW / Fused  : {m.dense_results:>4d} / {m.keyword_results:<4d} / {m.fused_results:<4d}   │\n"
            "└───────────────────────────────────────────────┘"
        )
        return m
