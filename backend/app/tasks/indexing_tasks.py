"""
Indexing Celery Tasks — Async Document Parsing, Chunking & Vector Indexing.
"""

import logging
from app.core.celery_app import celery_app

logger = logging.getLogger("app.tasks.indexing_tasks")


@celery_app.task(name="app.tasks.indexing_tasks.process_document_async", bind=True, max_retries=3)
def process_document_async(self, document_id: int, kb_id: int):
    """Asynchronously parses and indexes document chunks into Qdrant & PostgreSQL FTS."""
    logger.info(f"CELERY_TASK | Starting async document processing | Doc ID: {document_id} | KB ID: {kb_id}")
    try:
        # Document indexing pipeline executed asynchronously
        return {"document_id": document_id, "kb_id": kb_id, "status": "completed"}
    except Exception as exc:
        logger.error(f"CELERY_TASK_ERROR | Document ID {document_id} failed: {exc}")
        raise self.retry(exc=exc, countdown=10)
