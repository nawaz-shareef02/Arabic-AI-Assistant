"""
PrometheusExporter & MetricsRegistry — P2-3 Observability.

Centralized Metrics Registry Singleton with Enterprise Latency Buckets
covering HTTP, Database Pool, Redis, Celery, LLM/Ollama, and RAG metrics.

Design invariants:
- All metrics are process-local (no distributed state).
- No network I/O or DB queries inside metric recording calls.
- All labels are low-cardinality — no user/org/conversation IDs.
- DummyMetric fallback: app operates normally if prometheus_client is absent.
"""

import logging
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
        def dec(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass

    Counter = Histogram = Gauge = DummyMetric

    def generate_latest(*args, **kwargs): return b""

logger = logging.getLogger("app.core.prometheus_exporter")

# Enterprise latency histogram buckets covering sub-ms through 10 s.
# Covers: fast DB queries (5 ms), embedding (50 ms), RAG pipeline (500 ms–2 s),
# LLM generation (2 s–10 s+).
LATENCY_BUCKETS = (0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.0, 5.0, 10.0)


class MetricsRegistry:
    """
    Centralized Metrics Registry Singleton.

    Prevents duplicate Prometheus metric definitions across services.
    All metrics use low-cardinality labels — no user, org, conversation, or
    document IDs as labels. No IP addresses, prompts, or response content.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is not None:
            return cls._instance

        inst = super().__new__(cls)
        inst.registry = CollectorRegistry()

        # ── HTTP API Metrics ──────────────────────────────────────────────────
        # endpoint label = FastAPI route template (e.g. /api/v1/chat/{kb_id}),
        # NOT the raw URL, preventing unbounded cardinality from path parameters.
        inst.http_requests_total = Counter(
            "arabiq_http_requests_total",
            "Total HTTP requests by method, route template, and status code",
            ["method", "endpoint", "status"],
            registry=inst.registry,
        )
        inst.http_request_duration_seconds = Histogram(
            "arabiq_http_request_duration_seconds",
            "HTTP request wall-clock duration in seconds",
            ["method", "endpoint"],
            buckets=LATENCY_BUCKETS,
            registry=inst.registry,
        )

        # ── Security & Auth Metrics ───────────────────────────────────────────
        inst.failed_logins_total = Counter(
            "arabiq_security_failed_logins_total",
            "Total failed login attempts",
            registry=inst.registry,
        )
        inst.prompt_injections_total = Counter(
            "arabiq_security_prompt_injections_total",
            "Total prompt injection attempts detected",
            ["severity"],
            registry=inst.registry,
        )
        # limiter label = fixed names: login, register, api, chat, forgot_password, etc.
        inst.rate_limit_hits_total = Counter(
            "arabiq_security_rate_limit_hits_total",
            "Total rate limit block events by limiter name",
            ["limiter"],
            registry=inst.registry,
        )
        inst.blocked_uploads_total = Counter(
            "arabiq_security_blocked_uploads_total",
            "Total malicious or invalid file uploads blocked",
            registry=inst.registry,
        )

        # ── AI & RAG Sub-stage Metrics ────────────────────────────────────────
        # stage label = fixed set matching RetrievalMetrics fields:
        # query_expansion, embedding, dense_search, keyword_search, fusion,
        # filtering, rerank, prompt_build, llm, streaming
        inst.ai_stage_duration_seconds = Histogram(
            "arabiq_ai_stage_duration_seconds",
            "Duration of RAG pipeline sub-stages in seconds",
            ["stage"],
            buckets=LATENCY_BUCKETS,
            registry=inst.registry,
        )
        inst.ai_retrieval_result_count = Histogram(
            "arabiq_ai_retrieval_result_count",
            "Number of retrieved context documents returned per query",
            buckets=(1, 3, 5, 10, 20, 50),
            registry=inst.registry,
        )

        # ── LLM / Ollama Metrics ──────────────────────────────────────────────
        # model label = configured model name (e.g. "qwen3:8b") — bounded by
        # the number of deployed models, not by users or requests.
        # outcome label = success | timeout | error | cancelled
        # Never include: prompts, responses, user IDs, org IDs, doc IDs.
        inst.llm_requests_total = Counter(
            "arabiq_llm_requests_total",
            "Total LLM generation requests by model and outcome",
            ["model", "outcome"],
            registry=inst.registry,
        )
        inst.llm_generation_duration_seconds = Histogram(
            "arabiq_llm_generation_duration_seconds",
            "LLM generation duration in seconds "
            "(non-streaming: full response; streaming: until last token yielded)",
            ["model"],
            buckets=LATENCY_BUCKETS,
            registry=inst.registry,
        )
        inst.llm_first_token_seconds = Histogram(
            "arabiq_llm_first_token_seconds",
            "Time from LLM request start to first token received (streaming only)",
            ["model"],
            buckets=LATENCY_BUCKETS,
            registry=inst.registry,
        )
        # Sourced from Ollama eval_count field on the final response chunk.
        # Not recorded when Ollama does not return token counts.
        inst.llm_tokens_generated_total = Counter(
            "arabiq_llm_tokens_generated_total",
            "Tokens generated by LLM (from Ollama eval_count when available)",
            ["model"],
            registry=inst.registry,
        )
        # P2-4 Concurrency & Admission Control Metrics
        inst.llm_active_inferences = Gauge(
            "arabiq_llm_active_inferences",
            "Number of active concurrent LLM inference slots currently in use",
            ["model"],
            registry=inst.registry,
        )
        inst.llm_queue_rejections_total = Counter(
            "arabiq_llm_queue_rejections_total",
            "Total LLM inference requests rejected due to concurrency limit / capacity backpressure",
            ["model"],
            registry=inst.registry,
        )

        # ── Database Pool Metrics (P2-2 bridge) ──────────────────────────────
        # Gauges: updated on /metrics scrape via sync_db_pool_gauges() — zero I/O.
        # Counters: incremented by SQLAlchemy event hooks in database/session.py.
        inst.db_pool_size = Gauge(
            "arabiq_db_pool_size",
            "Configured connection pool size (process-local QueuePool)",
            registry=inst.registry,
        )
        inst.db_pool_checkedout = Gauge(
            "arabiq_db_pool_checkedout",
            "Connections currently checked out from pool (active)",
            registry=inst.registry,
        )
        inst.db_pool_checkedin = Gauge(
            "arabiq_db_pool_checkedin",
            "Connections currently idle in pool",
            registry=inst.registry,
        )
        inst.db_pool_overflow = Gauge(
            "arabiq_db_pool_overflow",
            "Connections currently in overflow (beyond pool_size)",
            registry=inst.registry,
        )
        inst.db_checkouts_total = Counter(
            "arabiq_db_checkouts_total",
            "Cumulative connection checkouts from pool",
            registry=inst.registry,
        )
        inst.db_checkins_total = Counter(
            "arabiq_db_checkins_total",
            "Cumulative connection checkins to pool",
            registry=inst.registry,
        )
        inst.db_pool_timeouts_total = Counter(
            "arabiq_db_pool_timeouts_total",
            "Cumulative pool timeout events (QueuePool exhaustion)",
            registry=inst.registry,
        )
        # Alias retained for any code referencing the old name.
        inst.db_active_connections = inst.db_pool_checkedout
        inst.db_query_duration_seconds = Histogram(
            "arabiq_db_query_duration_seconds",
            "Database query execution duration in seconds",
            buckets=LATENCY_BUCKETS,
            registry=inst.registry,
        )

        # ── Redis Metrics ─────────────────────────────────────────────────────
        inst.redis_cache_hits = Counter(
            "arabiq_redis_cache_hits_total",
            "Total Redis cache hits",
            registry=inst.registry,
        )
        inst.redis_cache_misses = Counter(
            "arabiq_redis_cache_misses_total",
            "Total Redis cache misses",
            registry=inst.registry,
        )
        inst.redis_connected_clients = Gauge(
            "arabiq_redis_connected_clients",
            "Current connected Redis clients",
            registry=inst.registry,
        )

        # ── Celery Metrics ────────────────────────────────────────────────────
        # status label = success | failure | retry
        # Semantics:
        #   success — task completed and returned successfully
        #   retry   — task raised a retryable exception; another attempt is scheduled
        #   failure — final failure after all retries exhausted, or permanent error
        # A single execution is counted as EITHER retry OR failure, never both.
        inst.celery_tasks_total = Counter(
            "arabiq_celery_tasks_total",
            "Celery task executions by outcome (success | retry | failure)",
            ["status"],
            registry=inst.registry,
        )
        inst.celery_task_duration_seconds = Histogram(
            "arabiq_celery_task_duration_seconds",
            "Celery task wall-clock execution duration in seconds",
            ["status"],
            buckets=LATENCY_BUCKETS,
            registry=inst.registry,
        )
        inst.celery_queue_depth = Gauge(
            "arabiq_celery_queue_depth",
            "Current pending tasks in Celery queue",
            registry=inst.registry,
        )

        cls._instance = inst
        return inst


# Module-level singleton — import and use directly.
metrics_registry = MetricsRegistry()


def sync_db_pool_gauges() -> None:
    """Refresh DB pool snapshot Gauges from PoolMetricsTracker.

    Invoked just before Prometheus text generation in get_prometheus_metrics_text().
    Zero network I/O — reads in-memory QueuePool state only.
    Exceptions are suppressed: a stale gauge is better than a failed /metrics scrape.
    """
    try:
        from app.database.session import get_pool_status
        s = get_pool_status()
        r = metrics_registry
        r.db_pool_size.set(s.get("pool_size", 0))
        r.db_pool_checkedout.set(s.get("checkedout", 0))
        r.db_pool_checkedin.set(s.get("checkedin", 0))
        r.db_pool_overflow.set(s.get("overflow", 0))
    except Exception:
        pass


def get_prometheus_metrics_text() -> bytes:
    """Generate Prometheus text format output for the /metrics endpoint."""
    sync_db_pool_gauges()
    return generate_latest(metrics_registry.registry)
