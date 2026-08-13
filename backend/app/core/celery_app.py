"""
Celery Application Module — Asynchronous Task Queue Manager.

Broker & Backend: Redis
Configured for background document processing, embedding generation,
scheduled backups, benchmark evaluations, and alert notifications.
"""

import os
import redis.connection
from celery import Celery
from app.core.config import settings

# Fix 'unknown command HELLO' on Windows native Redis 3.0.x by enforcing RESP2 protocol for all connection pools
_orig_pool_init = redis.connection.ConnectionPool.__init__

def _patched_pool_init(self, *args, **kwargs):
    kwargs.setdefault("protocol", 2)
    _orig_pool_init(self, *args, **kwargs)

redis.connection.ConnectionPool.__init__ = _patched_pool_init

celery_app = Celery(
    "arabiq",
    broker=getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=getattr(settings, "CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    include=[
        "app.tasks.indexing_tasks",
        "app.tasks.backup_tasks",
        "app.tasks.eval_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_max_tasks_per_child=100,
)
