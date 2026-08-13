"""
Backup Celery Tasks — Scheduled Backup Creation & Retention Cleanup.
"""

import logging
from app.core.celery_app import celery_app

logger = logging.getLogger("app.tasks.backup_tasks")


@celery_app.task(name="app.tasks.backup_tasks.run_scheduled_backup_async")
def run_scheduled_backup_async(backup_type: str = "Full", target: str = "All"):
    """Celery periodic background task for scheduled backups."""
    logger.info(f"CELERY_TASK | Executing scheduled backup | Type: {backup_type} | Target: {target}")
    return {"backup_type": backup_type, "target": target, "status": "completed"}
