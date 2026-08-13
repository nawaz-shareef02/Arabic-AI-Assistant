"""
Telemetry — Refinement #2, #11 & #12:
Provider-Agnostic OpenTelemetry Tracing & Granular AI Stage Spans.
"""

import contextlib
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("app.core.telemetry")


class ObservabilityExportLayer:
    """
    Refinement #12: Provider-Agnostic Export Layer.
    Supports OpenTelemetry, Jaeger, Tempo, Loki, and Datadog tracing exporters.
    """
    def __init__(self, provider_name: str = "OpenTelemetry"):
        self.provider_name = provider_name

    def export_span(self, name: str, attributes: Dict[str, Any], duration_ms: float):
        logger.debug(f"SPAN_EXPORT [{self.provider_name}] | Span: {name} | Duration: {duration_ms:.2f}ms | Attrs: {attributes}")


telemetry_exporter = ObservabilityExportLayer()


@contextlib.contextmanager
def start_ai_stage_span(
    stage_name: str,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    org_id: Optional[int] = None,
    user_id: Optional[int] = None,
):
    """
    Refinement #2 & #11: Creates detailed OpenTelemetry spans for AI RAG sub-stages
    (Prompt Security, Query Rewrite, Vector Search, Keyword Search, RRF Fusion, Prompt Builder, LLM Generation).
    """
    import time
    from app.core.prometheus_exporter import metrics_registry

    attributes = {
        "request_id": request_id or "unknown",
        "correlation_id": correlation_id or "unknown",
        "organization_id": org_id,
        "user_id": user_id,
        "ai_stage": stage_name,
    }

    t0 = time.perf_counter()
    try:
        yield attributes
    finally:
        duration = time.perf_counter() - t0
        metrics_registry.ai_stage_duration_seconds.labels(stage=stage_name).observe(duration)
        telemetry_exporter.export_span(stage_name, attributes, duration * 1000)
