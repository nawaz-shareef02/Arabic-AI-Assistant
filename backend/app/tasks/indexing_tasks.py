"""
Indexing Celery Tasks — Real Document Processing Pipeline.

P0-2 Security & Architecture Sprint.

This module replaces the stub task that returned {"status": "completed"}
without performing any work.  The task now implements the complete document
ingestion pipeline:

  SecurityScanner → Parser → normalize_text → ParsedDocument →
  ChunkService → EmbeddingService → QdrantService → status = PARSED

Architecture
------------
- Celery worker runs in a SEPARATE OS process from FastAPI.
- Each task invocation creates its own SQLAlchemy session via SessionLocal()
  and guarantees session closure in a finally block.
- No FastAPI request-scoped sessions are reused or leaked.

Retry Strategy
--------------
- max_retries = 3 for transient infra failures (DB, Qdrant, network).
- DocumentParsingError → FAILED immediately, no retry (permanent failure).
- Exponential backoff: 60s → 120s → 180s (capped at 300s).

Idempotency
-----------
- If doc.status == PARSED → skip (already complete).
- If doc.status == FAILED → skip (do not retry without intervention).
- If replaying after crash during PARSING/CHUNKING/INDEXING:
    - Delete existing ParsedDocument (cascades to chunks via ORM).
    - Qdrant uses upsert → no duplicate vectors created.
    - Restart cleanly from PARSING.

Status Transitions
------------------
  QUEUED → PARSING → CHUNKING → INDEXING → PARSED
                                          ↘ FAILED

The terminal state PARSED means "indexed and searchable" — it corresponds to
what the business calls "Completed".

Intelligence pipeline (metadata enrichment, entity extraction, relationships)
is dispatched as a separate Celery task (run_intelligence_pipeline) AFTER
successful indexing.  This keeps the indexing worker free for the next job.
"""

import logging
import time
import uuid as py_uuid

from app.core.celery_app import celery_app
from app.schemas.document import DocumentStatus

# ---------------------------------------------------------------------------
# Module-level imports — kept here so unittest.mock.patch can intercept them.
# All heavy work is done in the Celery worker process, not the FastAPI process.
# ---------------------------------------------------------------------------
from app.database.session import SessionLocal
from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.services.parser_service import (
    ParserService,
    normalize_text,
    detect_language_and_confidence,
)
from app.services.parsers.base import DocumentParsingError
from app.services.parsers.factory import ParserFactory
from app.services.chunk_service import ChunkService
from app.services.indexing_service import IndexingService
from app.utils.security_scanner import SecurityScanner

logger = logging.getLogger("app.tasks.indexing_tasks")

# Maximum characters allowed per document.
# At 600 chars/chunk this caps processing at ~8 333 chunks, which is well
# within Qdrant and embedding service limits on a single worker.
_MAX_CHARS = 5_000_000


@celery_app.task(
    name="app.tasks.indexing_tasks.process_document_async",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,                # Acknowledge ONLY after task completes.
    reject_on_worker_lost=True,    # Re-queue task if worker crashes mid-execution.
)
def process_document_async(self, document_id: int, knowledge_base_id: int):
    """
    Full document ingestion pipeline executed asynchronously by a Celery worker.

    Parameters
    ----------
    document_id : int
        Primary-key integer ID of the Document record.
    knowledge_base_id : int
        Primary-key integer ID of the parent KnowledgeBase.
        Passed explicitly so the worker does not need to join across tables.
    """
    task_start = time.perf_counter()
    db = SessionLocal()
    doc = None

    try:
        # ── 1. Fetch document ────────────────────────────────────────────────
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            logger.error(
                "CELERY_TASK | process_document_async | Doc ID: %s | "
                "Reason: Document not found in DB — abandoning task",
                document_id,
            )
            return  # Not retryable — document simply doesn't exist.

        # ── 2. Idempotency guard ─────────────────────────────────────────────
        if doc.status == DocumentStatus.PARSED:
            logger.info(
                "CELERY_TASK | process_document_async | Doc ID: %s | "
                "Status: already PARSED — skipping (idempotent)",
                document_id,
            )
            return

        if doc.status == DocumentStatus.FAILED:
            logger.warning(
                "CELERY_TASK | process_document_async | Doc ID: %s | "
                "Status: FAILED — not retrying without manual intervention",
                document_id,
            )
            return

        # If a previous attempt left a partial ParsedDocument (crash during
        # PARSING/CHUNKING/INDEXING), delete it so we start clean.
        # Chunk cascade is configured on ParsedDocument → DocumentChunk.
        if doc.parsed_document is not None:
            logger.info(
                "CELERY_TASK | process_document_async | Doc ID: %s | "
                "Detected stale ParsedDocument from previous attempt — purging.",
                document_id,
            )
            db.delete(doc.parsed_document)
            db.commit()
            db.refresh(doc)

        # ── 3. Security scan ─────────────────────────────────────────────────
        scanner = SecurityScanner()
        if not scanner.scan_file(doc.storage_path):
            doc.status = DocumentStatus.FAILED
            doc.error_message = "Security scan failed: file rejected."
            db.commit()
            logger.error(
                "AUDIT_CELERY | action: security_scan_failed | Doc: %s | "
                "Reason: scanner rejected file",
                document_id,
            )
            return  # Permanent failure — do not retry.

        # ── 4. PARSING ───────────────────────────────────────────────────────
        doc.status = DocumentStatus.PARSING
        db.commit()

        parser_service = ParserService()

        try:
            parse_result = parser_service.parse_document(doc.storage_path)
        except DocumentParsingError as exc:
            # Permanent failure — broken or unsupported file.  Do NOT retry.
            doc.status = DocumentStatus.FAILED
            doc.error_message = f"Parse error: {str(exc)[:490]}"
            db.commit()
            logger.error(
                "AUDIT_CELERY | action: doc_parse_failed | Doc: %s | Reason: %s",
                document_id,
                str(exc),
            )
            return  # Exit without re-raising → Celery won't auto-retry.

        clean_text = normalize_text(parse_result.text)

        # Resource guard: reject documents that would exceed the char cap.
        if len(clean_text) > _MAX_CHARS:
            doc.status = DocumentStatus.FAILED
            doc.error_message = (
                f"Document exceeds maximum allowed size "
                f"({len(clean_text):,} chars > {_MAX_CHARS:,} chars limit)."
            )
            db.commit()
            logger.error(
                "AUDIT_CELERY | action: doc_too_large | Doc: %s | Chars: %s",
                document_id,
                len(clean_text),
            )
            return

        lang, confidence = detect_language_and_confidence(clean_text)

        parser_obj = ParserFactory.get_parser(doc.storage_path)
        parser_name = parser_obj.__class__.__name__

        # Save ParsedDocument
        parsed_doc = ParsedDocument(
            document_id=doc.id,
            parsed_text=clean_text,
            parser_version=parser_name,
            language_confidence=confidence,
            char_count=len(clean_text),
            page_count=parse_result.page_count,
            processing_duration=time.perf_counter() - task_start,
        )
        db.add(parsed_doc)
        db.commit()
        db.refresh(parsed_doc)

        logger.info(
            "AUDIT_CELERY | action: doc_parsed | Doc: %s | Parser: %s | "
            "Pages: %s | Chars: %s | Lang: %s",
            document_id,
            parser_name,
            parse_result.page_count,
            len(clean_text),
            lang,
        )

        # ── 5. CHUNKING ──────────────────────────────────────────────────────
        doc.status = DocumentStatus.CHUNKING
        db.commit()

        chunk_service = ChunkService(db)
        chunk_count = chunk_service.create_chunks(parsed_doc)

        logger.info(
            "AUDIT_CELERY | action: chunks_created | Doc: %s | Chunks: %s",
            document_id,
            chunk_count,
        )

        # ── 6. EMBEDDING + QDRANT INDEXING ───────────────────────────────────
        # Set an intermediate status so operators can observe progress.
        doc.status = DocumentStatus.READY_FOR_PARSING  # Reuse as "INDEXING" marker.
        db.commit()

        # Refresh parsed_doc so the chunks relationship is loaded.
        db.refresh(parsed_doc)

        indexing_service = IndexingService(db)
        indexed_count = indexing_service.index_document(
            parsed_doc,
            knowledge_base_id=knowledge_base_id,
        )

        logger.info(
            "AUDIT_CELERY | action: vectors_indexed | Doc: %s | Vectors: %s | KB: %s",
            document_id,
            indexed_count,
            knowledge_base_id,
        )

        # ── 7. Finalize document metadata ────────────────────────────────────
        doc.chunk_count = chunk_count
        doc.language = lang
        doc.status = DocumentStatus.PARSED  # Terminal SUCCESS state.
        doc.error_message = None            # Clear any previous error on clean retry.
        db.commit()
        db.refresh(doc)

        total_duration = time.perf_counter() - task_start
        logger.info(
            "AUDIT_CELERY | action: doc_processing_complete | Doc: %s | "
            "KB: %s | Chunks: %s | Vectors: %s | Duration: %.2fs | Status: PARSED",
            document_id,
            knowledge_base_id,
            chunk_count,
            indexed_count,
            total_duration,
        )

        # Record success metrics — wrapped so they never interfere with task cleanup.
        try:
            from app.core.prometheus_exporter import metrics_registry
            metrics_registry.celery_tasks_total.labels(status="success").inc()
            metrics_registry.celery_task_duration_seconds.labels(
                status="success"
            ).observe(total_duration)
        except Exception:
            pass

        # ── 8. Dispatch intelligence pipeline (non-blocking, separate task) ──
        # run_intelligence_pipeline is a separate Celery task so the current
        # worker is freed immediately.  This replaces the threading.Thread call
        # that existed in document_service.process_document().
        try:
            run_intelligence_pipeline.delay(doc.id)
        except Exception as intel_exc:
            # Intelligence enrichment is optional / best-effort.
            # NEVER fail the indexing task because of it.
            logger.warning(
                "AUDIT_CELERY | action: intelligence_dispatch_failed | Doc: %s | "
                "Reason: %s (non-fatal — document is indexed and searchable)",
                document_id,
                intel_exc,
            )

        return {
            "document_id": document_id,
            "knowledge_base_id": knowledge_base_id,
            "status": "completed",
            "chunks": chunk_count,
            "vectors": indexed_count,
            "duration_seconds": round(total_duration, 2),
        }

    except Exception as exc:
        # ── Transient failure path (DB, Qdrant, network, OOM, etc.) ─────────
        error_str = f"{type(exc).__name__}: {str(exc)[:400]}"

        # Mark document as FAILED immediately so clients see a definitive state.
        # If Celery retries, the idempotency guard at step 2 will allow the
        # retry because status is NOT PARSED.
        if doc is not None:
            try:
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_str
                db.commit()
            except Exception as db_exc:
                logger.error(
                    "AUDIT_CELERY | action: failed_status_update_error | Doc: %s | "
                    "DB error: %s",
                    document_id,
                    db_exc,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

        logger.error(
            "AUDIT_CELERY | action: doc_processing_failed | Doc: %s | "
            "Attempt: %s/%s | Error: %s",
            document_id,
            self.request.retries + 1,
            self.max_retries + 1,
            error_str,
        )

        # Retry with exponential backoff (60s, 120s, 180s).
        # Setting status to QUEUED before retry so the idempotency guard
        # in the next attempt does not abort early.
        if self.request.retries < self.max_retries:
            if doc is not None:
                try:
                    doc.status = DocumentStatus.QUEUED
                    doc.error_message = f"Retrying after error: {error_str}"
                    db.commit()
                except Exception:
                    pass
            retry_delay = min(60 * (self.request.retries + 1), 300)
            # Count this attempt as a retry (NOT a final failure).
            try:
                from app.core.prometheus_exporter import metrics_registry
                elapsed = time.perf_counter() - task_start
                metrics_registry.celery_tasks_total.labels(status="retry").inc()
                metrics_registry.celery_task_duration_seconds.labels(
                    status="retry"
                ).observe(elapsed)
            except Exception:
                pass
            raise self.retry(exc=exc, countdown=retry_delay)

        # Max retries exhausted — leave status as FAILED.
        logger.error(
            "AUDIT_CELERY | action: doc_processing_exhausted | Doc: %s | "
            "All %s retries exhausted — document marked FAILED permanently.",
            document_id,
            self.max_retries,
        )
        # Count final exhaustion as a failure.
        try:
            from app.core.prometheus_exporter import metrics_registry
            elapsed = time.perf_counter() - task_start
            metrics_registry.celery_tasks_total.labels(status="failure").inc()
            metrics_registry.celery_task_duration_seconds.labels(
                status="failure"
            ).observe(elapsed)
        except Exception:
            pass

    finally:
        # Guaranteed session cleanup regardless of success or failure.
        try:
            db.close()
        except Exception as close_exc:
            logger.warning(
                "AUDIT_CELERY | action: session_close_error | Doc: %s | %s",
                document_id,
                close_exc,
            )


@celery_app.task(
    name="app.tasks.indexing_tasks.run_intelligence_pipeline",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def run_intelligence_pipeline(self, document_id: int):
    """
    Post-indexing intelligence enrichment: metadata, entities, relationships.

    This is a Celery task replacement for the threading.Thread that was
    previously spawned inside document_service.process_document().

    Runs as a separate Celery task so the indexing worker is freed immediately
    and intelligence enrichment does not block future indexing jobs.
    """
    from app.database.session import SessionLocal
    from app.services.metadata_enrichment_service import MetadataEnrichmentService
    from app.services.document_relationship_service import DocumentRelationshipService

    db = SessionLocal()
    try:
        logger.info(
            "AUDIT_CELERY | action: intelligence_pipeline_start | Doc: %s",
            document_id,
        )

        enrichment_svc = MetadataEnrichmentService(db)
        meta = enrichment_svc.enrich_document(document_id)

        rel_svc = DocumentRelationshipService(db)
        rels = rel_svc.detect_relationships(document_id)

        logger.info(
            "AUDIT_CELERY | action: intelligence_pipeline_complete | Doc: %s | "
            "Category: %s | Relationships: %s",
            document_id,
            getattr(meta, "classification", "unknown"),
            len(rels),
        )
        return {"document_id": document_id, "status": "enriched"}

    except Exception as exc:
        logger.error(
            "AUDIT_CELERY | action: intelligence_pipeline_failed | Doc: %s | "
            "Error: %s | Attempt: %s/%s",
            document_id,
            exc,
            self.request.retries + 1,
            self.max_retries + 1,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)

    finally:
        try:
            db.close()
        except Exception:
            pass
