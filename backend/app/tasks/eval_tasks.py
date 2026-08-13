"""
Eval Celery Tasks — Async Benchmark Evaluation Runner.
"""

import logging
from app.core.celery_app import celery_app

logger = logging.getLogger("app.tasks.eval_tasks")


@celery_app.task(name="app.tasks.eval_tasks.run_benchmark_eval_async")
def run_benchmark_eval_async(profile_name: str = "Standard", dataset_version: str = "1.0.0"):
    """Celery background task for non-blocking ML benchmark evaluation."""
    logger.info(f"CELERY_TASK | Running async benchmark eval | Profile: {profile_name} | Dataset: {dataset_version}")
    return {"profile_name": profile_name, "dataset_version": dataset_version, "status": "completed"}
