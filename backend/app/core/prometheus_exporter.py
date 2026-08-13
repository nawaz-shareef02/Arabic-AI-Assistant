"""
PrometheusExporter & MetricsRegistry — Refinements #1, #3, #4, #5, #6 & #7:
Centralized Metrics Registry Singleton with Enterprise Latency Buckets,
Database, Redis, Celery, and AI Quality Metrics Exporter.
"""

import time
import logging
from typing import Dict, Any, List
try:
    from prometheus_client import (  # type: ignore
        Counter,
        Histogram,
        Gauge,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class CollectorRegistry:
        pass

    class DummyMetric:
        def __init__(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
        def observe(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass

    Counter = Histogram = Gauge = DummyMetric
    def generate_latest(*args, **kwargs): return b""

logger = logging.getLogger("app.core.prometheus_exporter")

# Enterprise latency histogram buckets (Refinement #3)
LATENCY_BUCKETS = (0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.0, 5.0, 10.0)


class MetricsRegistry:
    """
    Refinement #1: Centralized Metrics Registry Singleton.
    Prevents duplicate Prometheus metric definitions across services.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MetricsRegistry, cls).__new__(cls)
            cls._instance.registry = CollectorRegistry()

            # HTTP API Metrics
            cls._instance.http_requests_total = Counter(
                "arabiq_http_requests_total",
                "Total HTTP requests received",
                ["method", "endpoint", "status"],
                registry=cls._instance.registry,
            )
            cls._instance.http_request_duration_seconds = Histogram(
                "arabiq_http_request_duration_seconds",
                "HTTP request duration in seconds",
                ["method", "endpoint"],
                buckets=LATENCY_BUCKETS,
                registry=cls._instance.registry,
            )

            # Security & Auth Metrics
            cls._instance.failed_logins_total = Counter(
                "arabiq_security_failed_logins_total",
                "Total failed login attempts",
                registry=cls._instance.registry,
            )
            cls._instance.prompt_injections_total = Counter(
                "arabiq_security_prompt_injections_total",
                "Total prompt injection attempts detected",
                ["severity"],
                registry=cls._instance.registry,
            )
            cls._instance.rate_limit_hits_total = Counter(
                "arabiq_security_rate_limit_hits_total",
                "Total rate limit block events",
                ["limiter"],
                registry=cls._instance.registry,
            )
            cls._instance.blocked_uploads_total = Counter(
                "arabiq_security_blocked_uploads_total",
                "Total malicious or invalid file uploads blocked",
                registry=cls._instance.registry,
            )

            # AI & RAG Sub-stage Metrics (Refinement #2 & #7)
            cls._instance.ai_stage_duration_seconds = Histogram(
                "arabiq_ai_stage_duration_seconds",
                "Duration of AI RAG sub-stages in seconds",
                ["stage"],
                buckets=LATENCY_BUCKETS,
                registry=cls._instance.registry,
            )
            cls._instance.ai_retrieval_result_count = Histogram(
                "arabiq_ai_retrieval_result_count",
                "Number of retrieved context documents per query",
                buckets=(1, 3, 5, 10, 20, 50),
                registry=cls._instance.registry,
            )

            # Database Metrics (Refinement #4)
            cls._instance.db_active_connections = Gauge(
                "arabiq_db_active_connections",
                "Current active PostgreSQL database connections",
                registry=cls._instance.registry,
            )
            cls._instance.db_query_duration_seconds = Histogram(
                "arabiq_db_query_duration_seconds",
                "Database query execution duration in seconds",
                buckets=LATENCY_BUCKETS,
                registry=cls._instance.registry,
            )

            # Redis Metrics (Refinement #5)
            cls._instance.redis_cache_hits = Counter(
                "arabiq_redis_cache_hits_total",
                "Total Redis cache hits",
                registry=cls._instance.registry,
            )
            cls._instance.redis_cache_misses = Counter(
                "arabiq_redis_cache_misses_total",
                "Total Redis cache misses",
                registry=cls._instance.registry,
            )
            cls._instance.redis_connected_clients = Gauge(
                "arabiq_redis_connected_clients",
                "Current connected Redis clients",
                registry=cls._instance.registry,
            )

            # Celery Metrics (Refinement #6)
            cls._instance.celery_tasks_total = Counter(
                "arabiq_celery_tasks_total",
                "Total Celery tasks executed",
                ["status"],
                registry=cls._instance.registry,
            )
            cls._instance.celery_queue_depth = Gauge(
                "arabiq_celery_queue_depth",
                "Current pending tasks in Celery queue",
                registry=cls._instance.registry,
            )

        return cls._instance


# Export global registry instance
metrics_registry = MetricsRegistry()


def get_prometheus_metrics_text() -> bytes:
    """Generates Prometheus format text output for /metrics endpoint."""
    return generate_latest(metrics_registry.registry)
