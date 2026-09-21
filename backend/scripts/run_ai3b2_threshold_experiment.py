"""
AI-3B.2 Relevance Threshold Optimization Experiment Runner
Sprint AI-3B.2 — Enterprise Relevance Threshold Evaluation

OBJECTIVE:
Determine whether pre-RRF dense cosine thresholding can safely reduce false
retrievals on unanswerable/negative queries without materially degrading positive
retrieval recall across the locked AI-3 benchmark corpus.

GOVERNING RULES:
- Read-only on production behavior.
- Zero production mutations to keyword_search(), hybrid_search(), RAGService, Qdrant schema, or RRF (k=60).
- Reuses existing SearchService, RetrievalProfiler, RetrievalEvaluationService,
  and locked AI-3 constants (CORPUS_CHUNKS, FULL_BENCHMARK_CASES, TENANT_ISOLATION_CASES).
- Completely isolated in-memory Qdrant instance with strict DB fixture cleanup.
- Evaluates 8 threshold levels: [0.00, 0.35, 0.40, 0.45, 0.48, 0.50, 0.52, 0.55].
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
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import numpy as np
import psutil
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import func, text

# Adjust paths so app can be imported directly
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
logger = logging.getLogger("ai3b2_experiment")

THRESHOLDS_TO_EVALUATE = [0.00, 0.35, 0.40, 0.45, 0.48, 0.50, 0.52, 0.55]


def calculate_positive_metrics(
    retrieved_uuids: List[str],
    ground_truth_uuids: List[str],
    eval_svc: RetrievalEvaluationService,
) -> Dict[str, float]:
    p1 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=1)
    p3 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    p5 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    p10 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    r1 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=1)
    r3 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    r5 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    r10 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    mrr_val = eval_svc.calculate_mrr(retrieved_uuids, ground_truth_uuids)

    hr1 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:1]) else 0.0
    hr3 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:3]) else 0.0
    hr5 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:5]) else 0.0
    hr10 = 1.0 if any(u in ground_truth_uuids for u in retrieved_uuids[:10]) else 0.0

    ndcg3 = eval_svc.calculate_ndcg_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    ndcg5 = eval_svc.calculate_ndcg_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    ndcg10 = eval_svc.calculate_ndcg_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    return {
        "p1": p1, "p3": p3, "p5": p5, "p10": p10,
        "r1": r1, "r3": r3, "r5": r5, "r10": r10,
        "mrr": mrr_val,
        "hr1": hr1, "hr3": hr3, "hr5": hr5, "hr10": hr10,
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


def run_ai3b2_experiment() -> Dict[str, Any]:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("=" * 80)
    print(f"AI-3B.2 RELEVANCE THRESHOLD EXPERIMENT — {timestamp}")
    print("=" * 80)

    # 1. Load locked AI-3 baseline for integrity comparison
    locked_baseline_path = os.path.join(os.path.dirname(__file__), "..", "ai3_full_benchmark_results.json")
    if not os.path.exists(locked_baseline_path):
        raise FileNotFoundError(f"Locked AI-3 baseline not found at {locked_baseline_path}")

    with open(locked_baseline_path, "r", encoding="utf-8") as f:
        locked_data = json.load(f)

    locked_hybrid_pos = locked_data["results_by_mode"]["hybrid"]["overall_positive_metrics"]
    locked_hybrid_neg = locked_data["results_by_mode"]["hybrid"]["negative_metrics"]

    print(f"[OK] Locked AI-3 baseline loaded successfully.")
    print(f"     Locked Baseline Recall@1: {locked_hybrid_pos['r1']*100:.2f}% | MRR: {locked_hybrid_pos['mrr']:.4f}")
    print(f"     Locked Baseline Negative False Retrieval: {locked_hybrid_neg['false_retrieval_rate']*100:.1f}%")

    process = psutil.Process()
    rss_before_mb = process.memory_info().rss / 1024 / 1024

    db = SessionLocal()
    search_service = SearchService(db)
    embedding_svc = EmbeddingService()
    eval_svc = RetrievalEvaluationService()

    # Get PostgreSQL version
    pg_version = db.execute(text("SELECT version();")).scalar()
    print(f"[*] PostgreSQL Environment: {pg_version}")

    # In-memory Qdrant client for deterministic dense retrieval
    qdrant_client = QdrantClient(":memory:")
    collection_name = "ai3b2_threshold_collection"
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

        # Seed 1 dummy chunk in Org-B/KB-B for tenant isolation testing
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

        # ── 2. Retrieval Execution & Threshold Sweep Evaluation ──
        print(f"\n[*] Beginning Pre-RRF Dense Threshold Sweep across {len(THRESHOLDS_TO_EVALUATE)} thresholds...")
        print(f"    Thresholds: {THRESHOLDS_TO_EVALUATE}")

        sweep_results: Dict[str, Any] = {}

        with patch.object(QdrantService, "_client", qdrant_client), \
             patch.object(search_service.qdrant_service, "collection_name", collection_name):

            # Pre-compute query retrieval base candidates (Dense + Keyword) once per case
            print("\n[*] Executing candidate retrieval for 50 benchmark cases...")
            case_base_retrieval: List[Dict[str, Any]] = []

            for case_idx, case in enumerate(FULL_BENCHMARK_CASES):
                query = case["query"]
                is_pos = case["type"] == "positive"
                relevant_eval_ids = case.get("relevant_chunks", [])
                gt_uuids = [eval_to_uuid[eid] for eid in relevant_eval_ids if eid in eval_to_uuid]

                profiler = RetrievalProfiler()
                t0 = time.perf_counter()

                # Step 1: Dense search via existing _dense_search()
                dense_results = search_service._dense_search(
                    query=query,
                    knowledge_base_id=kb_a.id,
                    organization_id=org_a.id,
                    top_k=10,
                    profiler=profiler,
                )

                # Step 2: Keyword search via production keyword_search()
                profiler.start("keyword_search")
                keyword_results = search_service.keyword_search(
                    query=query,
                    knowledge_base_id=kb_a.id,
                    organization_id=org_a.id,
                    top_k=10,
                )
                profiler.stop("keyword_search")

                t_retrieval_ms = (time.perf_counter() - t0) * 1000

                case_base_retrieval.append({
                    "case": case,
                    "gt_uuids": gt_uuids,
                    "dense_results": dense_results,
                    "keyword_results": keyword_results,
                    "embedding_ms": profiler.metrics.embedding_ms,
                    "dense_search_ms": profiler.metrics.dense_search_ms,
                    "keyword_search_ms": profiler.metrics.keyword_search_ms,
                    "t_retrieval_ms": t_retrieval_ms,
                })

            print(f"[OK] Base retrieval complete for all 50 cases.")

            pos_cases_count = len([c for c in FULL_BENCHMARK_CASES if c["type"] == "positive"])
            neg_cases_count = len([c for c in FULL_BENCHMARK_CASES if c["type"] == "negative"])

            # Now evaluate each threshold level
            for tau in THRESHOLDS_TO_EVALUATE:
                tau_str = f"{tau:.2f}"
                print(f"\n--- Evaluating Threshold tau = {tau_str} ---")

                pos_records = []
                neg_records = []
                profiling_records = []
                dense_before_counts = []
                dense_after_counts = []
                final_counts = []
                neg_top_scores_accepted = []

                for item in case_base_retrieval:
                    case = item["case"]
                    gt_uuids = item["gt_uuids"]
                    is_pos = case["type"] == "positive"
                    dense_candidates = item["dense_results"]
                    keyword_candidates = item["keyword_results"]

                    dense_before_counts.append(len(dense_candidates))

                    # Deep copy dense results so we don't mutate underlying SearchResult scores across sweeps
                    dense_copy = [
                        SearchResult(
                            chunk_id=r.chunk_id,
                            chunk_uuid=r.chunk_uuid,
                            parsed_document_id=r.parsed_document_id,
                            knowledge_base_id=r.knowledge_base_id,
                            chunk_index=r.chunk_index,
                            text=r.text,
                            char_count=r.char_count,
                            estimated_tokens=r.estimated_tokens,
                            score=float(r.score),  # Preserve raw Cosine score
                            vector_score=float(r.score),
                        )
                        for r in dense_candidates
                    ]

                    # Step 2: Apply threshold to RAW Qdrant cosine scores BEFORE RRF (preserving order)
                    filtered_dense = [r for r in dense_copy if r.score >= tau]
                    dense_after_counts.append(len(filtered_dense))

                    # Step 3: Reciprocal Rank Fusion via existing _reciprocal_rank_fusion (k=60)
                    t_f0 = time.perf_counter()
                    fused_results = search_service._reciprocal_rank_fusion(
                        dense_results=filtered_dense,
                        keyword_results=keyword_candidates,
                    )
                    fusion_ms = (time.perf_counter() - t_f0) * 1000

                    hybrid_results = fused_results[:10]
                    final_counts.append(len(hybrid_results))
                    total_ms = item["t_retrieval_ms"] + fusion_ms

                    profiling_records.append({
                        "embedding_ms": item["embedding_ms"],
                        "dense_search_ms": item["dense_search_ms"],
                        "keyword_search_ms": item["keyword_search_ms"],
                        "fusion_ms": fusion_ms,
                        "total_ms": total_ms,
                    })

                    retrieved_uuids = [r.chunk_uuid for r in hybrid_results]

                    if is_pos:
                        m = calculate_positive_metrics(retrieved_uuids, gt_uuids, eval_svc)
                        pos_records.append({
                            "case_id": case["case_id"],
                            "language": case["language"],
                            "category": case["category"],
                            "bilingual_mode": case.get("bilingual_mode"),
                            "metrics": m,
                            "dense_before": len(dense_candidates),
                            "dense_after": len(filtered_dense),
                            "final_count": len(hybrid_results),
                            "top_eval_ids": [uuid_to_eval.get(u, "UNKNOWN") for u in retrieved_uuids[:5]],
                        })
                    else:
                        neg_m = calculate_negative_metrics(hybrid_results)
                        neg_records.append({
                            "case_id": case["case_id"],
                            "metrics": neg_m,
                            "dense_before": len(dense_candidates),
                            "dense_after": len(filtered_dense),
                            "final_count": len(hybrid_results),
                            "top_eval_ids": [uuid_to_eval.get(u, "UNKNOWN") for u in retrieved_uuids[:5]],
                        })
                        if len(hybrid_results) > 0:
                            # Note raw cosine score of top accepted item
                            top_chunk_uuid = hybrid_results[0].chunk_uuid
                            matching_raw = [r.score for r in dense_candidates if r.chunk_uuid == top_chunk_uuid]
                            raw_score = matching_raw[0] if matching_raw else 0.0
                            neg_top_scores_accepted.append(raw_score)

                # Aggregate Positive Metrics
                all_pos_m = [r["metrics"] for r in pos_records]
                avg_pos_m = {
                    k: float(np.mean([m[k] for m in all_pos_m]))
                    for k in all_pos_m[0].keys()
                }

                # Subgroup Breakdowns
                ar_15 = [r["metrics"] for r in pos_records if r["case_id"].startswith("AI3-AR-")]
                en_15 = [r["metrics"] for r in pos_records if r["case_id"].startswith("AI3-EN-")]
                bi_10 = [r["metrics"] for r in pos_records if r["case_id"].startswith("AI3-BI-")]
                mc_5 = [r["metrics"] for r in pos_records if r["case_id"].startswith("AI3-MC-")]

                def calc_avg(sub_list):
                    if not sub_list:
                        return {}
                    return {k: float(np.mean([m[k] for m in sub_list])) for k in sub_list[0].keys()}

                bi_ar2en = [r["metrics"] for r in pos_records if r.get("bilingual_mode") == "ar_to_en"]
                bi_en2ar = [r["metrics"] for r in pos_records if r.get("bilingual_mode") == "en_to_ar"]
                bi_mixed = [r["metrics"] for r in pos_records if r.get("bilingual_mode") == "mixed_to_mixed"]

                # Aggregate Negative Metrics
                all_neg_m = [r["metrics"] for r in neg_records]
                avg_neg_m = {
                    "no_result_rate": float(np.mean([m["no_result"] for m in all_neg_m])),
                    "false_retrieval_rate": float(np.mean([m["false_retrieval"] for m in all_neg_m])),
                    "cases_count": len(all_neg_m),
                    "avg_accepted_top_score": float(np.mean(neg_top_scores_accepted)) if neg_top_scores_accepted else 0.0,
                    "max_accepted_top_score": float(np.max(neg_top_scores_accepted)) if neg_top_scores_accepted else 0.0,
                    "count_false_retrieved": len(neg_top_scores_accepted),
                }

                # Latency & Profiling Summary
                totals = [p["total_ms"] for p in profiling_records]
                timing_summary = {
                    "min_ms": float(np.min(totals)),
                    "p50_ms": float(np.percentile(totals, 50)),
                    "p95_ms": float(np.percentile(totals, 95)),
                    "max_ms": float(np.max(totals)),
                    "mean_ms": float(np.mean(totals)),
                    "avg_embedding_ms": float(np.mean([p["embedding_ms"] for p in profiling_records])),
                    "avg_dense_ms": float(np.mean([p["dense_search_ms"] for p in profiling_records])),
                    "avg_keyword_ms": float(np.mean([p["keyword_search_ms"] for p in profiling_records])),
                    "avg_fusion_ms": float(np.mean([p["fusion_ms"] for p in profiling_records])),
                }

                # Candidate Counts
                candidate_summary = {
                    "avg_dense_before_threshold": float(np.mean(dense_before_counts)),
                    "avg_dense_after_threshold": float(np.mean(dense_after_counts)),
                    "avg_final_returned": float(np.mean(final_counts)),
                }

                # Tenant Isolation Verification at threshold tau
                tenant_test_results = []
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

                    tenant_test_results.append({
                        "case_name": tc["name"],
                        "expected": expected,
                        "outcome": outcome,
                    })

                tenant_passed = f"{sum(1 for t in tenant_test_results if t['outcome'] == 'PASS')}/6"

                sweep_results[tau_str] = {
                    "threshold": tau,
                    "overall_positive_metrics": avg_pos_m,
                    "subgroup_metrics": {
                        "arabic_15": calc_avg(ar_15),
                        "english_15": calc_avg(en_15),
                        "bilingual_10": calc_avg(bi_10),
                        "bilingual_ar_to_en_3": calc_avg(bi_ar2en),
                        "bilingual_en_to_ar_3": calc_avg(bi_en2ar),
                        "bilingual_mixed_4": calc_avg(bi_mixed),
                        "multi_chunk_5": calc_avg(mc_5),
                    },
                    "negative_metrics": avg_neg_m,
                    "candidate_counts": candidate_summary,
                    "tenant_isolation_passed": tenant_passed,
                    "tenant_isolation_details": tenant_test_results,
                    "timings": timing_summary,
                }

                print(f"    R@1: {avg_pos_m['r1']*100:.2f}% | R@3: {avg_pos_m['r3']*100:.2f}% | R@5: {avg_pos_m['r5']*100:.2f}% | MRR: {avg_pos_m['mrr']:.4f}")
                print(f"    Negative False Retrieval Rate: {avg_neg_m['false_retrieval_rate']*100:.1f}% ({avg_neg_m['count_false_retrieved']}/5) | No-Result Rate: {avg_neg_m['no_result_rate']*100:.1f}%")
                print(f"    Avg Dense Candidates: Before={candidate_summary['avg_dense_before_threshold']:.1f} -> After={candidate_summary['avg_dense_after_threshold']:.1f}")
                print(f"    Tenant Isolation: {tenant_passed}")

        # Baseline 0.00 Integrity Check vs. Locked AI-3 Baseline
        t0_results = sweep_results["0.00"]["overall_positive_metrics"]
        delta_r1 = abs(t0_results["r1"] - locked_hybrid_pos["r1"])
        delta_mrr = abs(t0_results["mrr"] - locked_hybrid_pos["mrr"])

        print(f"\n[*] Quality Check: Comparing Threshold 0.00 against Locked AI-3 Hybrid Baseline:")
        print(f"    Delta Recall@1: {delta_r1:.6f} | Delta MRR: {delta_mrr:.6f}")
        assert delta_r1 < 1e-6, f"Baseline reproduction mismatch on R@1: delta={delta_r1}"
        assert delta_mrr < 1e-6, f"Baseline reproduction mismatch on MRR: delta={delta_mrr}"
        print("    [PASS] Threshold 0.00 exactly matches locked AI-3 hybrid baseline.")

        # Construct full report artifact
        report_artifact = {
            "metadata": {
                "benchmark_name": "AI-3B.2 Relevance Threshold Optimization Experiment",
                "timestamp": timestamp,
                "environment": {
                    "platform": platform.platform(),
                    "python_version": sys.version,
                    "postgresql_version": pg_version,
                    "vector_engine": "In-memory deterministic Qdrant (Distance.COSINE, dim=1024)",
                    "embedding_model": "BAAI/bge-m3",
                },
                "threshold_list": THRESHOLDS_TO_EVALUATE,
                "corpus_chunks_count": len(CORPUS_CHUNKS),
                "positive_cases_count": pos_cases_count,
                "negative_cases_count": neg_cases_count,
                "total_cases_count": len(FULL_BENCHMARK_CASES),
            },
            "locked_baseline_hybrid": {
                "recall_at_1": locked_hybrid_pos["r1"],
                "mrr": locked_hybrid_pos["mrr"],
                "false_retrieval_rate": locked_hybrid_neg["false_retrieval_rate"],
            },
            "threshold_sweep_results": sweep_results,
            "methodology": (
                "For each query, dense vector search (Qdrant Cosine) and keyword search (PostgreSQL FTS) "
                "retrieve candidate pools. The pre-RRF relevance threshold is applied strictly to raw "
                "Qdrant cosine scores (score >= threshold), discarding sub-threshold chunks while preserving "
                "relative candidate order. Surviving dense candidates and keyword candidates are then fused "
                "via the existing Reciprocal Rank Fusion implementation (k=60). In-memory Qdrant instance "
                "guarantees zero persistent storage mutation."
            ),
            "limitations": (
                "Evaluated on a controlled 30-chunk benchmark corpus covering Saudi Labor Law, PDPL, and HR policies. "
                "Real-world enterprise corpora with noisy documents, multi-tenant variations, or domain shifts "
                "may require dynamic or calibrated thresholding."
            ),
        }

        output_path = os.path.join(os.path.dirname(__file__), "..", "ai3b2_threshold_experiment_results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_artifact, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] AI-3B.2 experiment results successfully written to {output_path}")

        return report_artifact

    finally:
        # Strict database fixture cleanup
        print("[*] Cleaning up database test fixtures...")
        if created_chunk_ids:
            db.query(DocumentChunk).filter(DocumentChunk.id.in_(created_chunk_ids)).delete(synchronize_session=False)
        if created_pdoc_ids:
            db.query(ParsedDocument).filter(ParsedDocument.id.in_(created_pdoc_ids)).delete(synchronize_session=False)
        if created_doc_ids:
            db.query(Document).filter(Document.id.in_(created_doc_ids)).delete(synchronize_session=False)
        if org_a.id and org_b.id:
            db.query(KnowledgeBase).filter(KnowledgeBase.organization_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
            db.query(Organization).filter(Organization.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()
        db.close()
        print("[OK] Test fixtures completely cleaned up.")


if __name__ == "__main__":
    run_ai3b2_experiment()
