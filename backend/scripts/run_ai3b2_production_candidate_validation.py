"""
AI-3B.2 Follow-Up: Production-Candidate Validation Runner
Senior Enterprise Retrieval Review

OBJECTIVE:
Determine whether pre-RRF dense cosine thresholding at tau=0.48 and tau=0.50
could damage legitimate keyword/hybrid retrieval behavior across:
1. Dense-only relevant queries
2. Keyword-heavy/exact-match queries
3. Exact technical terms
4. Acronyms
5. Policy/document identifiers
6. Organization-specific terminology
7. Queries where keyword search returns a relevant result but dense similarity is below 0.48/0.50
8. Queries where both dense and keyword retrieval return the same relevant document
9. Negative/unanswerable queries
10. Tenant-isolation cases

STRICT GOVERNANCE RULES:
- Read-only on production behavior.
- Zero mutations to SearchService, keyword_search(), hybrid_search(), RAGService, Qdrant schema, or RRF (k=60).
- Reuses existing SearchService, RetrievalProfiler, RetrievalEvaluationService, and CORPUS_CHUNKS.
- Explicitly separates the Locked AI-3 Benchmark (50 cases) from Supplemental Engineering Probes (32 cases).
- Strictly isolated in-memory Qdrant instance with comprehensive PostgreSQL fixture cleanup.
"""

import copy
import json
import logging
import os
import platform
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Set
from unittest.mock import patch

# Force UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import psutil
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import func, text

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Adjust path so backend app can be imported directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.parsed_document import ParsedDocument
from app.models.user import User
from app.services.ai_performance_service import RetrievalEvaluationService
from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService
from app.services.retrieval_profiler import RetrievalProfiler
from app.services.search_service import SearchResult, SearchService

from scripts.run_ai3_full_benchmark import (
    CORPUS_CHUNKS,
    FULL_BENCHMARK_CASES,
    TENANT_ISOLATION_CASES,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ai3b2_validation")

THRESHOLDS = [0.00, 0.48, 0.50]

# ──────────────────────────────────────────────────────────────────────────────
# SUPPLEMENTAL ENGINEERING PROBES (Strictly Separated from Locked AI-3 Suite)
# ──────────────────────────────────────────────────────────────────────────────
SUPPLEMENTAL_ENGINEERING_PROBES = [
    # ── Category 1: Dense-Only Relevant Queries (semantic variation, 0 keyword match) ──
    {
        "probe_id": "PROBE-CAT01-01",
        "category": "Cat 1: Dense-only relevant",
        "type": "positive",
        "query": "how does the platform avoid running out of database connections under high traffic?",
        "relevant_chunks": ["arch_database_pooling"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT01-02",
        "category": "Cat 1: Dense-only relevant",
        "type": "positive",
        "query": "ما هي مستحقات نهاية الخدمة عند الاستقالة الإرادية؟",
        "relevant_chunks": ["legal_labor_art85"],
        "lang": "ar",
    },
    {
        "probe_id": "PROBE-CAT01-03",
        "category": "Cat 1: Dense-only relevant",
        "type": "positive",
        "query": "quarantine process for background indexing jobs that fail repeatedly",
        "relevant_chunks": ["arch_celery_dlq"],
        "lang": "en",
    },

    # ── Category 2: Keyword-Heavy / Exact-Match Queries ──
    {
        "probe_id": "PROBE-CAT02-01",
        "category": "Cat 2: Keyword-heavy / exact-match",
        "type": "positive",
        "query": "Celery Redis",
        "relevant_chunks": ["arch_celery_redis"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT02-02",
        "category": "Cat 2: Keyword-heavy / exact-match",
        "type": "positive",
        "query": "AES-256 TLS 1.3",
        "relevant_chunks": ["sec_encryption_standards"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT02-03",
        "category": "Cat 2: Keyword-heavy / exact-match",
        "type": "positive",
        "query": "المادة الثمانون من نظام العمل الجزاءات التأديبية",
        "relevant_chunks": ["hr_disciplinary_code"],
        "lang": "ar",
    },

    # ── Category 3: Exact Technical Terms ──
    {
        "probe_id": "PROBE-CAT03-01",
        "category": "Cat 3: Exact technical terms",
        "type": "positive",
        "query": "SHA-256",
        "relevant_chunks": ["arch_storage_dedup"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT03-02",
        "category": "Cat 3: Exact technical terms",
        "type": "positive",
        "query": "Reciprocal Rank Fusion RRF",
        "relevant_chunks": ["arch_hybrid_search"],
        "lang": "bi",
    },
    {
        "probe_id": "PROBE-CAT03-03",
        "category": "Cat 3: Exact technical terms",
        "type": "positive",
        "query": "SQLAlchemy connection pooling",
        "relevant_chunks": ["arch_database_pooling"],
        "lang": "en",
    },

    # ── Category 4: Acronyms ──
    {
        "probe_id": "PROBE-CAT04-01",
        "category": "Cat 4: Acronyms",
        "type": "positive",
        "query": "DLQ",
        "relevant_chunks": ["arch_celery_dlq"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT04-02",
        "category": "Cat 4: Acronyms",
        "type": "positive",
        "query": "RBAC",
        "relevant_chunks": ["sec_rbac_isolation"],
        "lang": "bi",
    },
    {
        "probe_id": "PROBE-CAT04-03",
        "category": "Cat 4: Acronyms",
        "type": "positive",
        "query": "SDAIA",
        "relevant_chunks": ["legal_pdpl_breach"],
        "lang": "bi",
    },

    # ── Category 5: Policy / Document Identifiers ──
    {
        "probe_id": "PROBE-CAT05-01",
        "category": "Cat 5: Policy / document identifiers",
        "type": "positive",
        "query": "Tier-2",
        "relevant_chunks": ["hr_expense_reimbursement"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT05-02",
        "category": "Cat 5: Policy / document identifiers",
        "type": "positive",
        "query": "المادة الرابعة والثمانون",
        "relevant_chunks": ["legal_labor_art84"],
        "lang": "ar",
    },
    {
        "probe_id": "PROBE-CAT05-03",
        "category": "Cat 5: Policy / document identifiers",
        "type": "positive",
        "query": "المادة الخامسة والثمانون",
        "relevant_chunks": ["legal_labor_art85"],
        "lang": "ar",
    },
    {
        "probe_id": "PROBE-CAT05-04",
        "category": "Cat 5: Policy / document identifiers",
        "type": "positive",
        "query": "المادة السابعة والسبعون",
        "relevant_chunks": ["legal_labor_art77"],
        "lang": "ar",
    },
    {
        "probe_id": "PROBE-CAT05-05",
        "category": "Cat 5: Policy / document identifiers",
        "type": "positive",
        "query": "المادة الثامنة والتسعون",
        "relevant_chunks": ["legal_labor_art98"],
        "lang": "ar",
    },

    # ── Category 6: Organization-Specific Terminology ──
    {
        "probe_id": "PROBE-CAT06-01",
        "category": "Cat 6: Organization-specific terminology",
        "type": "positive",
        "query": "ArabIQ flexible workplace",
        "relevant_chunks": ["hr_remote_work"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT06-02",
        "category": "Cat 6: Organization-specific terminology",
        "type": "positive",
        "query": "ArabIQ security audit log",
        "relevant_chunks": ["sec_audit_trail"],
        "lang": "bi",
    },

    # ── Category 7: Keyword Relevant Result But Dense Similarity < 0.48/0.50 (KEY RISK PROBE) ──
    {
        "probe_id": "PROBE-CAT07-01",
        "category": "Cat 7: Keyword relevant but dense sim < 0.48",
        "type": "positive",
        "query": "DLQ",
        "relevant_chunks": ["arch_celery_dlq"],
        "lang": "en",
        "expected_dense_sim_approx": 0.4602,
    },
    {
        "probe_id": "PROBE-CAT07-02",
        "category": "Cat 7: Keyword relevant but dense sim < 0.48",
        "type": "positive",
        "query": "Tier-2",
        "relevant_chunks": ["hr_expense_reimbursement"],
        "lang": "en",
        "expected_dense_sim_approx": 0.4372,
    },
    {
        "probe_id": "PROBE-CAT07-03",
        "category": "Cat 7: Keyword relevant but dense sim < 0.48",
        "type": "positive",
        "query": "المادة الرابعة والثمانون",
        "relevant_chunks": ["legal_labor_art84"],
        "lang": "ar",
        "expected_dense_sim_approx": 0.4321,
    },
    {
        "probe_id": "PROBE-CAT07-04",
        "category": "Cat 7: Keyword relevant but dense sim < 0.48",
        "type": "positive",
        "query": "المادة الخامسة والثمانون",
        "relevant_chunks": ["legal_labor_art85"],
        "lang": "ar",
        "expected_dense_sim_approx": 0.4586,
    },
    {
        "probe_id": "PROBE-CAT07-05",
        "category": "Cat 7: Keyword relevant but dense sim < 0.48",
        "type": "positive",
        "query": "المادة السابعة والسبعون",
        "relevant_chunks": ["legal_labor_art77"],
        "lang": "ar",
        "expected_dense_sim_approx": 0.4627,
    },
    {
        "probe_id": "PROBE-CAT07-06",
        "category": "Cat 7: Keyword relevant but dense sim < 0.48",
        "type": "positive",
        "query": "المادة الثامنة والتسعون",
        "relevant_chunks": ["legal_labor_art98"],
        "lang": "ar",
        "expected_dense_sim_approx": 0.3995,
    },

    # ── Category 8: Queries Where Both Dense and Keyword Return Same Relevant Chunk ──
    {
        "probe_id": "PROBE-CAT08-01",
        "category": "Cat 8: Dense+Keyword dual reinforcement",
        "type": "positive",
        "query": "SHA-256",
        "relevant_chunks": ["arch_storage_dedup"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT08-02",
        "category": "Cat 8: Dense+Keyword dual reinforcement",
        "type": "positive",
        "query": "RBAC",
        "relevant_chunks": ["sec_rbac_isolation"],
        "lang": "bi",
    },
    {
        "probe_id": "PROBE-CAT08-03",
        "category": "Cat 8: Dense+Keyword dual reinforcement",
        "type": "positive",
        "query": "ArabIQ flexible workplace",
        "relevant_chunks": ["hr_remote_work"],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT08-04",
        "category": "Cat 8: Dense+Keyword dual reinforcement",
        "type": "positive",
        "query": "Reciprocal Rank Fusion RRF",
        "relevant_chunks": ["arch_hybrid_search"],
        "lang": "bi",
    },

    # ── Category 9: Negative / Unanswerable Queries ──
    {
        "probe_id": "PROBE-CAT09-01",
        "category": "Cat 9: Negative / unanswerable",
        "type": "negative",
        "query": "Kubernetes Helm charts deployment on AWS EKS",
        "relevant_chunks": [],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT09-02",
        "category": "Cat 9: Negative / unanswerable",
        "type": "negative",
        "query": "سياسة منح القروض الشخصية وسلف الموظفين",
        "relevant_chunks": [],
        "lang": "ar",
    },
    {
        "probe_id": "PROBE-CAT09-03",
        "category": "Cat 9: Negative / unanswerable",
        "type": "negative",
        "query": "GraphQL Apollo federation schema gateway",
        "relevant_chunks": [],
        "lang": "en",
    },
    {
        "probe_id": "PROBE-CAT09-04",
        "category": "Cat 9: Negative / unanswerable",
        "type": "negative",
        "query": "ضريبة القيمة المضافة وإقرارات هيئة الزكاة والضريبة والجمارك",
        "relevant_chunks": [],
        "lang": "ar",
    },
    {
        "probe_id": "PROBE-CAT09-05",
        "category": "Cat 9: Negative / unanswerable",
        "type": "negative",
        "query": "Apache Kafka partition reassignment and consumer group rebalance",
        "relevant_chunks": [],
        "lang": "en",
    },
]


def calculate_metrics(
    retrieved_uuids: List[str],
    ground_truth_uuids: List[str],
    eval_svc: RetrievalEvaluationService,
) -> Dict[str, float]:
    r1 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=1)
    r3 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    r5 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    r10 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    p1 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=1)
    p3 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    p5 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    p10 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    mrr_val = eval_svc.calculate_mrr(retrieved_uuids, ground_truth_uuids)

    hr1 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:1]) else 0.0
    hr3 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:3]) else 0.0
    hr5 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:5]) else 0.0

    ndcg3 = eval_svc.calculate_ndcg_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    ndcg5 = eval_svc.calculate_ndcg_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    ndcg10 = eval_svc.calculate_ndcg_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    return {
        "r1": r1, "r3": r3, "r5": r5, "r10": r10,
        "p1": p1, "p3": p3, "p5": p5, "p10": p10,
        "mrr": mrr_val,
        "hr1": hr1, "hr3": hr3, "hr5": hr5,
        "ndcg3": ndcg3, "ndcg5": ndcg5, "ndcg10": ndcg10,
    }


def calculate_negative_metrics(search_results: List[SearchResult]) -> Dict[str, Any]:
    count = len(search_results)
    no_result = 1.0 if count == 0 else 0.0
    false_retrieval = 1.0 if count > 0 else 0.0
    top_score = float(search_results[0].score) if count > 0 else 0.0
    return {
        "count_retrieved": count,
        "no_result": no_result,
        "false_retrieval": false_retrieval,
        "top_irrelevant_score": top_score,
    }


def clone_results(results: List[SearchResult]) -> List[SearchResult]:
    """Create fresh SearchResult instances with raw scores preserved to prevent mutation by RRF."""
    return [
        SearchResult(
            chunk_id=r.chunk_id,
            chunk_uuid=r.chunk_uuid,
            parsed_document_id=r.parsed_document_id,
            knowledge_base_id=r.knowledge_base_id,
            chunk_index=r.chunk_index,
            text=r.text,
            char_count=r.char_count,
            estimated_tokens=r.estimated_tokens,
            score=float(r.vector_score if r.vector_score is not None else (r.keyword_score if r.keyword_score is not None else r.score)),
            vector_score=float(r.vector_score) if r.vector_score is not None else None,
            keyword_score=float(r.keyword_score) if r.keyword_score is not None else None,
            document_id=r.document_id,
            document_name=r.document_name,
            language=r.language,
        )
        for r in results
    ]


def run_production_candidate_validation():
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("=" * 80)
    print(f"AI-3B.2 PRODUCTION-CANDIDATE VALIDATION — {timestamp}")
    print("=" * 80)

    db = SessionLocal()
    search_service = SearchService(db)
    embedding_svc = EmbeddingService()
    eval_svc = RetrievalEvaluationService()

    # Ephemeral in-memory Qdrant client
    qdrant_client = QdrantClient(":memory:")
    collection_name = "ai3b2_prod_cand_collection"
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

    test_uid = uuid.uuid4().hex[:8]
    org_a = Organization(name=f"AI3B2 Org A {test_uid}", slug=f"ai3b2-org-a-{test_uid}")
    org_b = Organization(name=f"AI3B2 Org B {test_uid}", slug=f"ai3b2-org-b-{test_uid}")
    db.add_all([org_a, org_b])
    db.commit()

    created_doc_ids: List[int] = []
    created_pdoc_ids: List[int] = []
    created_chunk_ids: List[int] = []
    eval_to_uuid: Dict[str, str] = {}
    uuid_to_eval: Dict[str, str] = {}

    try:
        user = db.query(User).first()
        user_id = user.id if user else 1

        kb_a = KnowledgeBase(name=f"AI3B2 KB A {test_uid}", organization_id=org_a.id, owner_id=user_id)
        kb_b = KnowledgeBase(name=f"AI3B2 KB B {test_uid}", organization_id=org_b.id, owner_id=user_id)
        db.add_all([kb_a, kb_b])
        db.commit()

        print(f"[*] Seeding {len(CORPUS_CHUNKS)} canonical benchmark chunks in Org-A/KB-A...")
        doc_a = Document(
            filename="ai3b2_corpus.txt",
            storage_path="/experiment/corpus",
            mime_type="text/plain",
            file_size=20000,
            knowledge_base_id=kb_a.id,
            created_by=user_id,
            status="Processed",
        )
        db.add(doc_a)
        db.commit()
        created_doc_ids.append(doc_a.id)

        pdoc_a = ParsedDocument(
            document_id=doc_a.id,
            parsed_text=" ".join(c["text"] for c in CORPUS_CHUNKS),
            char_count=sum(len(c["text"]) for c in CORPUS_CHUNKS),
            processing_duration=1.0,
        )
        db.add(pdoc_a)
        db.commit()
        created_pdoc_ids.append(pdoc_a.id)

        points = []
        for idx, chunk_def in enumerate(CORPUS_CHUNKS):
            eval_id = chunk_def["eval_id"]
            text_content = chunk_def["text"]

            chunk_obj = DocumentChunk(
                parsed_document_id=pdoc_a.id,
                chunk_index=idx,
                chunk_text=text_content,
                char_count=len(text_content),
                estimated_tokens=len(text_content.split()),
                start_offset=0,
                end_offset=len(text_content),
                search_vector=func.to_tsvector("simple", text_content),
            )
            db.add(chunk_obj)
            db.commit()
            created_chunk_ids.append(chunk_obj.id)
            eval_to_uuid[eval_id] = str(chunk_obj.uuid)
            uuid_to_eval[str(chunk_obj.uuid)] = eval_id

            vec = embedding_svc.embed_text(text_content)
            points.append(
                PointStruct(
                    id=chunk_obj.id,
                    vector=vec,
                    payload={
                        "chunk_uuid": str(chunk_obj.uuid),
                        "parsed_document_id": pdoc_a.id,
                        "knowledge_base_id": kb_a.id,
                        "organization_id": org_a.id,
                        "chunk_index": idx,
                        "text": text_content,
                        "char_count": len(text_content),
                        "estimated_tokens": len(text_content.split()),
                    },
                )
            )

        qdrant_client.upsert(collection_name=collection_name, points=points)
        print(f"[OK] Seeded and indexed {len(points)} chunks in Org-A/KB-A.")

        # Seed Org-B chunk for tenant isolation verification
        doc_b = Document(
            filename="org_b_private.txt",
            storage_path="/experiment/org_b",
            mime_type="text/plain",
            file_size=500,
            knowledge_base_id=kb_b.id,
            created_by=user_id,
            status="Processed",
        )
        db.add(doc_b)
        db.commit()
        created_doc_ids.append(doc_b.id)

        org_b_text = "Enterprise security policy and internal compliance guidelines for Organization B."
        pdoc_b = ParsedDocument(
            document_id=doc_b.id,
            parsed_text=org_b_text,
            char_count=len(org_b_text),
            processing_duration=0.1,
        )
        db.add(pdoc_b)
        db.commit()
        created_pdoc_ids.append(pdoc_b.id)

        chunk_b = DocumentChunk(
            parsed_document_id=pdoc_b.id,
            chunk_index=0,
            chunk_text=org_b_text,
            char_count=len(org_b_text),
            estimated_tokens=10,
            start_offset=0,
            end_offset=len(org_b_text),
            search_vector=func.to_tsvector("simple", org_b_text),
        )
        db.add(chunk_b)
        db.commit()
        created_chunk_ids.append(chunk_b.id)

        qdrant_client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=chunk_b.id,
                    vector=embedding_svc.embed_text(org_b_text),
                    payload={
                        "chunk_uuid": str(chunk_b.uuid),
                        "parsed_document_id": pdoc_b.id,
                        "knowledge_base_id": kb_b.id,
                        "organization_id": org_b.id,
                        "chunk_index": 0,
                        "text": org_b_text,
                        "char_count": len(org_b_text),
                        "estimated_tokens": 10,
                    },
                )
            ],
        )
        print("[OK] Multi-tenant fixture seeding complete.")

        # ──────────────────────────────────────────────────────────────────────
        # EVALUATION EXECUTION ACROSS BOTH SUITES
        # ──────────────────────────────────────────────────────────────────────
        results_payload: Dict[str, Any] = {
            "metadata": {
                "timestamp": timestamp,
                "thresholds_evaluated": THRESHOLDS,
                "environment": {
                    "os": platform.platform(),
                    "python": sys.version.split()[0],
                    "cpu_count": psutil.cpu_count(logical=True),
                },
                "locked_ai3_corpus_limitation_documented": True,
            },
            "suite_1_locked_ai3": {},
            "suite_2_supplemental_probes": {},
            "tenant_isolation_results": {},
            "category_level_analysis": {},
        }

        with patch.object(QdrantService, "_client", qdrant_client), \
             patch.object(search_service.qdrant_service, "collection_name", collection_name):

            # ══════════════════════════════════════════════════════════════════
            # SUITE 1: LOCKED AI-3 BENCHMARK (50 Cases)
            # ══════════════════════════════════════════════════════════════════
            print("\n" + "=" * 60)
            print("RUNNING SUITE 1: LOCKED AI-3 BENCHMARK (50 Cases)")
            print("=" * 60)

            # Pre-retrieve base candidates for Suite 1
            suite1_candidates: List[Dict[str, Any]] = []
            for case in FULL_BENCHMARK_CASES:
                query = case["query"]
                dense_cand = search_service._dense_search(
                    query=query, knowledge_base_id=kb_a.id, organization_id=org_a.id, top_k=10
                )
                for r in dense_cand:
                    r.vector_score = float(r.score)

                kw_cand = search_service.keyword_search(
                    query=query, knowledge_base_id=kb_a.id, organization_id=org_a.id, top_k=10
                )
                for r in kw_cand:
                    r.keyword_score = float(r.score)

                relevant_eval_ids = case.get("relevant_chunks", [])
                gt_uuids = [eval_to_uuid[eid] for eid in relevant_eval_ids if eid in eval_to_uuid]

                suite1_candidates.append({
                    "case": case,
                    "gt_uuids": gt_uuids,
                    "dense_candidates": dense_cand,
                    "keyword_candidates": kw_cand,
                })

            # Record baseline results to measure retention
            suite1_baseline_pos_top5_uuids: Dict[str, Set[str]] = {}
            suite1_baseline_kw_only_cases: List[str] = []
            suite1_dense_kw_overlap_cases: List[str] = []

            for item in suite1_candidates:
                case = item["case"]
                case_id = case["case_id"]
                is_pos = case["type"] == "positive"
                d_cand = clone_results(item["dense_candidates"])
                k_cand = clone_results(item["keyword_candidates"])
                gt_uuids = set(item["gt_uuids"])

                # Check overlap
                d_uuids = set(r.chunk_uuid for r in d_cand)
                k_uuids = set(r.chunk_uuid for r in k_cand)
                if any(u in gt_uuids for u in d_uuids) and any(u in gt_uuids for u in k_uuids):
                    suite1_dense_kw_overlap_cases.append(case_id)
                elif not any(u in gt_uuids for u in d_uuids) and any(u in gt_uuids for u in k_uuids):
                    suite1_baseline_kw_only_cases.append(case_id)

                # Fused at tau=0.00
                fused_baseline = search_service._reciprocal_rank_fusion(d_cand, k_cand)[:5]
                if is_pos:
                    suite1_baseline_pos_top5_uuids[case_id] = set(
                        u for u in [r.chunk_uuid for r in fused_baseline] if u in gt_uuids
                    )

            for tau in THRESHOLDS:
                tau_str = f"{tau:.2f}"
                pos_m_list = []
                neg_m_list = []
                retention_list = []
                kw_retention_list = []
                dense_before_counts = []
                dense_after_counts = []
                final_counts = []
                per_case_details = []

                for item in suite1_candidates:
                    case = item["case"]
                    case_id = case["case_id"]
                    gt_uuids = item["gt_uuids"]
                    is_pos = case["type"] == "positive"
                    d_cand = clone_results(item["dense_candidates"])
                    k_cand = clone_results(item["keyword_candidates"])

                    dense_before_counts.append(len(d_cand))
                    filtered_dense = [r for r in d_cand if r.score >= tau]
                    dense_after_counts.append(len(filtered_dense))

                    fused = search_service._reciprocal_rank_fusion(filtered_dense, k_cand)
                    top5 = fused[:5]
                    top10 = fused[:10]
                    final_counts.append(len(top5))

                    retrieved_top5_uuids = [r.chunk_uuid for r in top5]
                    retrieved_top10_uuids = [r.chunk_uuid for r in top10]

                    if is_pos:
                        m = calculate_metrics(retrieved_top10_uuids, gt_uuids, eval_svc)
                        pos_m_list.append(m)

                        # Relevant result retention relative to tau=0.00 top-5
                        base_relevant = suite1_baseline_pos_top5_uuids.get(case_id, set())
                        if len(base_relevant) > 0:
                            current_relevant = set(u for u in retrieved_top5_uuids if u in gt_uuids)
                            ret_rate = len(current_relevant.intersection(base_relevant)) / len(base_relevant)
                        else:
                            ret_rate = 1.0
                        retention_list.append(ret_rate)

                        # Keyword-only retention
                        if case_id in suite1_baseline_kw_only_cases:
                            kw_retention_list.append(ret_rate)

                        per_case_details.append({
                            "case_id": case_id,
                            "r1": m["r1"], "r3": m["r3"], "r5": m["r5"], "mrr": m["mrr"],
                            "dense_before": len(d_cand), "dense_after": len(filtered_dense),
                            "final_count": len(top5),
                        })
                    else:
                        neg_m = calculate_negative_metrics(top5)
                        neg_m_list.append(neg_m)

                avg_pos = {k: float(np.mean([m[k] for m in pos_m_list])) for k in pos_m_list[0].keys()}
                avg_neg = {
                    "no_result_rate": float(np.mean([m["no_result"] for m in neg_m_list])),
                    "false_retrieval_rate": float(np.mean([m["false_retrieval"] for m in neg_m_list])),
                    "false_retrieval_count": int(sum(m["false_retrieval"] for m in neg_m_list)),
                    "total_negative_cases": len(neg_m_list),
                }

                suite1_summary = {
                    "threshold": tau,
                    "recall_at_1": avg_pos["r1"],
                    "recall_at_3": avg_pos["r3"],
                    "recall_at_5": avg_pos["r5"],
                    "mrr": avg_pos["mrr"],
                    "ndcg_at_3": avg_pos["ndcg3"],
                    "ndcg_at_5": avg_pos["ndcg5"],
                    "ndcg_at_10": avg_pos["ndcg10"],
                    "relevant_result_retention_rate": float(np.mean(retention_list)),
                    "keyword_only_result_retention_rate": float(np.mean(kw_retention_list)) if kw_retention_list else 1.0,
                    "dense_keyword_overlap_count": len(suite1_dense_kw_overlap_cases),
                    "negative_false_retrieval_rate": avg_neg["false_retrieval_rate"],
                    "negative_false_retrieval_count": avg_neg["false_retrieval_count"],
                    "no_result_rate_on_positive": float(np.mean([1.0 if c["final_count"] == 0 else 0.0 for c in per_case_details])),
                    "candidate_counts": {
                        "avg_dense_before": float(np.mean(dense_before_counts)),
                        "avg_dense_after": float(np.mean(dense_after_counts)),
                        "avg_final_top5": float(np.mean(final_counts)),
                    },
                }
                results_payload["suite_1_locked_ai3"][tau_str] = suite1_summary

                print(f"[Suite 1 Locked AI-3] tau={tau_str}: R@1={avg_pos['r1']*100:.2f}% | R@3={avg_pos['r3']*100:.2f}% | MRR={avg_pos['mrr']:.4f} | NegFalse={avg_neg['false_retrieval_count']}/{len(neg_m_list)} | Retention={suite1_summary['relevant_result_retention_rate']*100:.2f}%")

            # ══════════════════════════════════════════════════════════════════
            # SUITE 2: SUPPLEMENTAL ENGINEERING PROBES (32 Cases)
            # ══════════════════════════════════════════════════════════════════
            print("\n" + "=" * 60)
            print("RUNNING SUITE 2: SUPPLEMENTAL ENGINEERING PROBES (32 Cases)")
            print("=" * 60)

            suite2_candidates: List[Dict[str, Any]] = []
            for probe in SUPPLEMENTAL_ENGINEERING_PROBES:
                query = probe["query"]
                dense_cand = search_service._dense_search(
                    query=query, knowledge_base_id=kb_a.id, organization_id=org_a.id, top_k=10
                )
                for r in dense_cand:
                    r.vector_score = float(r.score)

                kw_cand = search_service.keyword_search(
                    query=query, knowledge_base_id=kb_a.id, organization_id=org_a.id, top_k=10
                )
                for r in kw_cand:
                    r.keyword_score = float(r.score)

                relevant_eval_ids = probe.get("relevant_chunks", [])
                gt_uuids = [eval_to_uuid[eid] for eid in relevant_eval_ids if eid in eval_to_uuid]

                suite2_candidates.append({
                    "probe": probe,
                    "gt_uuids": gt_uuids,
                    "dense_candidates": dense_cand,
                    "keyword_candidates": kw_cand,
                })

            suite2_baseline_pos_top5_uuids: Dict[str, Set[str]] = {}
            suite2_baseline_kw_only_cases: List[str] = []
            suite2_dense_kw_overlap_cases: List[str] = []

            for item in suite2_candidates:
                probe = item["probe"]
                probe_id = probe["probe_id"]
                is_pos = probe["type"] == "positive"
                d_cand = clone_results(item["dense_candidates"])
                k_cand = clone_results(item["keyword_candidates"])
                gt_uuids = set(item["gt_uuids"])

                d_uuids = set(r.chunk_uuid for r in d_cand)
                k_uuids = set(r.chunk_uuid for r in k_cand)
                if any(u in gt_uuids for u in d_uuids) and any(u in gt_uuids for u in k_uuids):
                    suite2_dense_kw_overlap_cases.append(probe_id)
                elif not any(u in gt_uuids for u in d_uuids) and any(u in gt_uuids for u in k_uuids):
                    suite2_baseline_kw_only_cases.append(probe_id)

                fused_baseline = search_service._reciprocal_rank_fusion(d_cand, k_cand)[:5]
                if is_pos:
                    suite2_baseline_pos_top5_uuids[probe_id] = set(
                        u for u in [r.chunk_uuid for r in fused_baseline] if u in gt_uuids
                    )

            for tau in THRESHOLDS:
                tau_str = f"{tau:.2f}"
                pos_m_list = []
                neg_m_list = []
                retention_list = []
                kw_retention_list = []
                dense_before_counts = []
                dense_after_counts = []
                final_counts = []
                per_probe_details = []

                for item in suite2_candidates:
                    probe = item["probe"]
                    probe_id = probe["probe_id"]
                    gt_uuids = item["gt_uuids"]
                    is_pos = probe["type"] == "positive"
                    d_cand = clone_results(item["dense_candidates"])
                    k_cand = clone_results(item["keyword_candidates"])

                    dense_before_counts.append(len(d_cand))
                    filtered_dense = [r for r in d_cand if r.score >= tau]
                    dense_after_counts.append(len(filtered_dense))

                    fused = search_service._reciprocal_rank_fusion(filtered_dense, k_cand)
                    top5 = fused[:5]
                    top10 = fused[:10]
                    final_counts.append(len(top5))

                    retrieved_top5_uuids = [r.chunk_uuid for r in top5]
                    retrieved_top10_uuids = [r.chunk_uuid for r in top10]

                    if is_pos:
                        m = calculate_metrics(retrieved_top10_uuids, gt_uuids, eval_svc)
                        pos_m_list.append(m)

                        base_relevant = suite2_baseline_pos_top5_uuids.get(probe_id, set())
                        if len(base_relevant) > 0:
                            current_relevant = set(u for u in retrieved_top5_uuids if u in gt_uuids)
                            ret_rate = len(current_relevant.intersection(base_relevant)) / len(base_relevant)
                        else:
                            ret_rate = 1.0
                        retention_list.append(ret_rate)

                        if probe_id in suite2_baseline_kw_only_cases:
                            kw_retention_list.append(ret_rate)

                        # Inspect top rank item
                        top_eval = uuid_to_eval.get(top5[0].chunk_uuid, "NONE") if top5 else "NONE"

                        per_probe_details.append({
                            "probe_id": probe_id,
                            "category": probe["category"],
                            "query": probe["query"],
                            "r1": m["r1"], "r3": m["r3"], "r5": m["r5"], "mrr": m["mrr"],
                            "ndcg5": m["ndcg5"],
                            "dense_before": len(d_cand), "dense_after": len(filtered_dense),
                            "final_count": len(top5),
                            "top_eval": top_eval,
                        })
                    else:
                        neg_m = calculate_negative_metrics(top5)
                        neg_m_list.append(neg_m)

                avg_pos = {k: float(np.mean([m[k] for m in pos_m_list])) for k in pos_m_list[0].keys()}
                avg_neg = {
                    "no_result_rate": float(np.mean([m["no_result"] for m in neg_m_list])),
                    "false_retrieval_rate": float(np.mean([m["false_retrieval"] for m in neg_m_list])),
                    "false_retrieval_count": int(sum(m["false_retrieval"] for m in neg_m_list)),
                    "total_negative_cases": len(neg_m_list),
                }

                suite2_summary = {
                    "threshold": tau,
                    "recall_at_1": avg_pos["r1"],
                    "recall_at_3": avg_pos["r3"],
                    "recall_at_5": avg_pos["r5"],
                    "mrr": avg_pos["mrr"],
                    "ndcg_at_3": avg_pos["ndcg3"],
                    "ndcg_at_5": avg_pos["ndcg5"],
                    "ndcg_at_10": avg_pos["ndcg10"],
                    "relevant_result_retention_rate": float(np.mean(retention_list)),
                    "keyword_only_result_retention_rate": float(np.mean(kw_retention_list)) if kw_retention_list else 1.0,
                    "dense_keyword_overlap_count": len(suite2_dense_kw_overlap_cases),
                    "negative_false_retrieval_rate": avg_neg["false_retrieval_rate"],
                    "negative_false_retrieval_count": avg_neg["false_retrieval_count"],
                    "no_result_rate_on_positive": float(np.mean([1.0 if c["final_count"] == 0 else 0.0 for c in per_probe_details])),
                    "candidate_counts": {
                        "avg_dense_before": float(np.mean(dense_before_counts)),
                        "avg_dense_after": float(np.mean(dense_after_counts)),
                        "avg_final_top5": float(np.mean(final_counts)),
                    },
                    "per_probe_results": per_probe_details,
                }
                results_payload["suite_2_supplemental_probes"][tau_str] = suite2_summary

                print(f"[Suite 2 Probes] tau={tau_str}: R@1={avg_pos['r1']*100:.2f}% | R@3={avg_pos['r3']*100:.2f}% | MRR={avg_pos['mrr']:.4f} | NegFalse={avg_neg['false_retrieval_count']}/{len(neg_m_list)} | Retention={suite2_summary['relevant_result_retention_rate']*100:.2f}%")

            # ══════════════════════════════════════════════════════════════════
            # CATEGORY-LEVEL BREAKDOWN ON SUPPLEMENTAL PROBES
            # ══════════════════════════════════════════════════════════════════
            categories = sorted(list(set(p["category"] for p in SUPPLEMENTAL_ENGINEERING_PROBES if p["type"] == "positive")))
            cat_analysis: Dict[str, Any] = {}

            for cat in categories:
                cat_probes = [p for p in results_payload["suite_2_supplemental_probes"]["0.00"]["per_probe_results"] if p["category"] == cat]
                cat_analysis[cat] = {}
                for tau in THRESHOLDS:
                    tau_str = f"{tau:.2f}"
                    curr_probes = [p for p in results_payload["suite_2_supplemental_probes"][tau_str]["per_probe_results"] if p["category"] == cat]
                    cat_analysis[cat][tau_str] = {
                        "r1": float(np.mean([p["r1"] for p in curr_probes])),
                        "r3": float(np.mean([p["r3"] for p in curr_probes])),
                        "r5": float(np.mean([p["r5"] for p in curr_probes])),
                        "mrr": float(np.mean([p["mrr"] for p in curr_probes])),
                        "ndcg5": float(np.mean([p["ndcg5"] for p in curr_probes])),
                        "avg_final_count": float(np.mean([p["final_count"] for p in curr_probes])),
                        "cases": [
                            {
                                "probe_id": p["probe_id"],
                                "query": p["query"],
                                "r1": p["r1"],
                                "top_eval": p["top_eval"],
                            }
                            for p in curr_probes
                        ]
                    }

            results_payload["category_level_analysis"] = cat_analysis

            # ══════════════════════════════════════════════════════════════════
            # TENANT ISOLATION VALIDATION
            # ══════════════════════════════════════════════════════════════════
            print("\n" + "=" * 60)
            print("RUNNING TENANT ISOLATION VALIDATION (6 Canonical Cases)")
            print("=" * 60)

            for tau in THRESHOLDS:
                tau_str = f"{tau:.2f}"
                t_records = []
                for tc in TENANT_ISOLATION_CASES:
                    org_param = org_a.id if tc["org"] == "A" else (org_b.id if tc["org"] == "B" else None)
                    kb_param = kb_a.id if tc["kb"] == "A" else (kb_b.id if tc["kb"] == "B" else None)
                    expected = tc["expected"]
                    outcome = "UNKNOWN"

                    try:
                        d_res = search_service._dense_search(
                            query="enterprise security policy",
                            knowledge_base_id=kb_param,
                            organization_id=org_param,
                            top_k=5,
                        )
                        k_res = search_service.keyword_search(
                            query="enterprise security policy",
                            knowledge_base_id=kb_param,
                            organization_id=org_param,
                            top_k=5,
                        )
                        f_dense = [r for r in d_res if r.score >= tau]
                        f_res = search_service._reciprocal_rank_fusion(f_dense, k_res)
                        res_count = len(f_res[:5])
                        if expected == "permitted":
                            outcome = "PASS" if res_count > 0 else "FAIL_EMPTY"
                        elif expected == "denied":
                            outcome = "PASS" if res_count == 0 else "FAIL_LEAK"
                    except ValueError:
                        outcome = "PASS" if expected == "fail_closed" else "UNEXPECTED_ERROR"
                    except Exception:
                        outcome = "UNEXPECTED_ERROR"

                    t_records.append({
                        "case_name": tc["name"],
                        "expected": expected,
                        "outcome": outcome,
                    })

                passed_count = sum(1 for t in t_records if t["outcome"] == "PASS")
                results_payload["tenant_isolation_results"][tau_str] = {
                    "passed": f"{passed_count}/6",
                    "all_passed": passed_count == 6,
                    "details": t_records,
                }
                print(f"[Tenant Isolation] tau={tau_str}: {passed_count}/6 passed.")

        # Save JSON output artifact
        output_path = os.path.join(os.path.dirname(__file__), "..", "ai3b2_production_candidate_validation_results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results_payload, f, indent=2, ensure_ascii=False)

        print(f"\n[OK] Validation completed successfully. Output saved to {output_path}")

    finally:
        # Strict DB Cleanup
        print("[*] Performing database fixture cleanup...")
        try:
            if created_chunk_ids:
                db.query(DocumentChunk).filter(DocumentChunk.id.in_(created_chunk_ids)).delete(synchronize_session=False)
            if created_pdoc_ids:
                db.query(ParsedDocument).filter(ParsedDocument.id.in_(created_pdoc_ids)).delete(synchronize_session=False)
            if created_doc_ids:
                db.query(Document).filter(Document.id.in_(created_doc_ids)).delete(synchronize_session=False)
            db.delete(kb_a)
            db.delete(kb_b)
            db.delete(org_a)
            db.delete(org_b)
            db.commit()
            print("[OK] Database cleanup completed successfully.")
        except Exception as e:
            print(f"[!] Warning during DB cleanup: {e}")
            db.rollback()
        finally:
            db.close()


if __name__ == "__main__":
    run_production_candidate_validation()
