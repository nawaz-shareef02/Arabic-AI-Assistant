"""
Celery Application Module — Asynchronous Task Queue Manager.

Broker & Backend: Redis (configured from environment/settings)
Tasks:
  - app.tasks.indexing_tasks  — document parsing, chunking, embedding, Qdrant indexing
  - app.tasks.backup_tasks    — scheduled database backups
  - app.tasks.eval_tasks      — benchmark / evaluation jobs

Configuration notes
-------------------
- CELERY_BROKER_URL defaults to redis://localhost:6379/1
- CELERY_RESULT_BACKEND defaults to redis://localhost:6379/2
- No production secrets are hardcoded; all values read from settings / environment.
- Redis RESP2 protocol is enforced to fix the 'unknown command HELLO' error on
  Windows-native Redis 3.0.x builds.
"""

import redis.connection
from celery import Celery
from app.core.config import settings

# ---------------------------------------------------------------------------
# Windows Redis RESP2 compatibility fix.
# Enforces RESP2 protocol for all connection pools to avoid the
# 'unknown command HELLO' error on Redis 3.0.x (Windows native).
# ---------------------------------------------------------------------------
_orig_pool_init = redis.connection.ConnectionPool.__init__


def _patched_pool_init(self, *args, **kwargs):
    kwargs.setdefault("protocol", 2)
    _orig_pool_init(self, *args, **kwargs)


redis.connection.ConnectionPool.__init__ = _patched_pool_init

# ---------------------------------------------------------------------------
# Celery application instance.
# ---------------------------------------------------------------------------
celery_app = Celery(
    "arabiq",
    broker=getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=getattr(settings, "CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    include=[
        "app.tasks.indexing_tasks",   # Document processing + intelligence pipeline
        "app.tasks.backup_tasks",
        "app.tasks.eval_tasks",
    ],
)

celery_app.conf.update(
    # ── Serialization ────────────────────────────────────────────────────────
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # ── Time zone ────────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,

    # ── Reliability ──────────────────────────────────────────────────────────
    # Track task lifecycle (PENDING → STARTED → SUCCESS/FAILURE).
    task_track_started=True,

    # Hard wall clock limit per task (3 600 s = 1 hour).
    # Document processing should complete well within this window.
    task_time_limit=3600,

    # Soft limit — sends SIGTERM before SIGKILL so the task can clean up.
    task_soft_time_limit=3300,

    # Acknowledge task ONLY after it completes (prevents silent data loss on
    # worker crash).  Must be paired with reject_on_worker_lost=True on the
    # individual task decorator.
    task_acks_late=True,

    # ── Worker hygiene ───────────────────────────────────────────────────────
    # Restart worker child process after N tasks to reclaim memory.
    # Document processing (especially embedding) can grow memory significantly.
    worker_max_tasks_per_child=50,

    # Prefetch 1 task at a time so workers with long-running tasks do not
    # monopolise the queue for other workers that are idle.
    worker_prefetch_multiplier=1,

    # ── Result backend ───────────────────────────────────────────────────────
    # Keep results for 24 h; after that they expire from Redis automatically.
    result_expires=86400,
)

# ---------------------------------------------------------------------------
# Celery Worker Fork Safety
# ---------------------------------------------------------------------------
from celery.signals import worker_process_init

@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """
    Ensure each forked Celery worker child process disposes any inherited
    SQLAlchemy engine sockets and starts with an isolated, clean connection pool.
    """
    try:
        from app.database.session import reset_engine_pool
        reset_engine_pool()
    except Exception as exc:
        import logging
        logging.getLogger("app.core.celery_app").warning(f"Error resetting DB engine pool post-fork: {exc}")

