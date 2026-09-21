"""
AI-3 Pre-Benchmark 15-Case Retrieval Smoke Benchmark Runner.

Evaluates Pure Retrieval (No LLM generation):
- Dense (BGE-M3 + Qdrant)
- Keyword (PostgreSQL FTS)
- Hybrid (Dense + Keyword + RRF)

Distribution:
- 5 Arabic cases
- 5 English cases
- 5 Bilingual cases

Metrics:
- Recall@3, Recall@5, Recall@10
- Precision@3, Precision@5, Precision@10
- MRR
- Hit Rate@3, Hit Rate@5, Hit Rate@10
- Profiling: embedding_ms, dense_search_ms, keyword_search_ms, fusion_ms, total_retrieval_ms
- Latencies: min, p50, p95, max
- Memory: RSS before, peak, after
"""

import os
import sys
import time
import json
import uuid

# Force UTF-8 on Windows stdout/stderr
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from typing import Dict, List, Any
import numpy as np
import psutil
from sqlalchemy import func
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.session import SessionLocal
from app.models.organization import Organization
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.models.chunk import DocumentChunk
from app.services.search_service import SearchService, SearchResult
from app.services.qdrant_service import QdrantService
from app.services.embedding_service import EmbeddingService
from app.services.ai_performance_service import RetrievalEvaluationService
from app.services.retrieval_profiler import RetrievalProfiler
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct


# ──────────────────────────────────────────────────────────────────────────────
# Benchmark Corpus Definition (Deterministic Stable Identifiers)
# ──────────────────────────────────────────────────────────────────────────────

BENCHMARK_CHUNKS = [
    {
        "eval_id": "labor_law_art84",
        "title": "Saudi Labor Law Article 84",
        "text": "تنص المادة الرابعة والثمانون من نظام العمل السعودي على أنه إذا انتهت علاقة العمل وجب على صاحب العمل أن يدفع إلى العامل مكافأة عن مدة خدمته تحسب على أساس أجر نصف شهر عن كل سنة من السنوات الخمس الأولى، وأجر شهر عن كل سنة من السنوات التالية، ويتخذ الأجر الأخير أساساً لحساب المكافأة، ويستحق العامل مكافأة عن أجزاء السنة بنسبة ما قضاه منها في العمل.",
        "lang": "ar",
    },
    {
        "eval_id": "labor_law_art85",
        "title": "Saudi Labor Law Article 85",
        "text": "تنص المادة الخامسة والثمانون من نظام العمل السعودي على استحقاق العامل ثلث المكافأة بعد خدمة لا تقل عن سنتين متتاليتين ولا تزيد على خمس سنوات، وثلثيها إذا زادت مدة خدمته على خمس سنوات متتالية ولم تبلغ عشر سنوات، ويستحق المكافأة كاملة إذا بلغت مدة خدمته عشر سنوات فأكثر في حال الاستقالة.",
        "lang": "ar",
    },
    {
        "eval_id": "sec_policy_rbac",
        "title": "Role-Based Access Control Policy",
        "text": "تعتمد منصة ArabIQ نظام التحكم في الوصول القائم على الأدوار RBAC مع عزل كامل للمنظمات، حيث يمنع أي مستخدم من الوصول إلى قواعد معرفة تابعة لمنظمة أخرى لضمان أمان البيانات متعددة المستأجرين.",
        "lang": "ar",
    },
    {
        "eval_id": "hr_leave_policy",
        "title": "Enterprise HR Leave Policy",
        "text": "تحدد سياسة الموارد البشرية الإجازة السنوية المدفوعة بـ 30 يوماً للموظفين الذين أكملوا خمس سنوات في الخدمة، و21 يوماً لمن تقل خدمتهم عن ذلك، مع إلزامية الحصول على موافقة مسبقة.",
        "lang": "ar",
    },
    {
        "eval_id": "sec_policy_audit",
        "title": "Security Audit Trail",
        "text": "The ArabIQ security audit log records all user authentication, authorization, prompt security decisions, and cross-tenant access attempts with SHA-256 integrity and strict organization boundary isolation لسجلات التدقيق الأمني ومراقبة المحاولات المشبوهة.",
        "lang": "bi",
    },
    {
        "eval_id": "arch_hybrid_search",
        "title": "Hybrid Search Architecture",
        "text": "ArabIQ hybrid search architecture fuses dense embeddings from BAAI/bge-m3 with PostgreSQL GIN tsvector full-text search using Reciprocal Rank Fusion RRF with constant k=60 to balance lexical and semantic precision وحساب الترتيب التبادلي.",
        "lang": "bi",
    },
    {
        "eval_id": "arch_qdrant_vector",
        "title": "Qdrant Vector Database Engine",
        "text": "Vector retrieval is implemented via Qdrant with cosine distance on 1024-dimensional embeddings. Payload indexes on organization_id and knowledge_base_id enforce strict multi-tenant partitioning وعزل المنظمات.",
        "lang": "bi",
    },
    {
        "eval_id": "cloud_celery_redis",
        "title": "Asynchronous Processing Queue",
        "text": "The asynchronous document ingestion pipeline employs Celery workers backed by Redis for task dispatch, concurrency admission control, and distributed leasing to handle batch uploads reliably.",
        "lang": "en",
    },
    {
        "eval_id": "arch_database_pooling",
        "title": "Database Connection Management",
        "text": "Database connection management utilizes SQLAlchemy connection pooling with proactive checkout release before remote LLM or vector DB network calls, preventing PostgreSQL connection exhaustion under load.",
        "lang": "en",
    },
    {
        "eval_id": "sec_prompt_injection",
        "title": "Prompt Injection Defense",
        "text": "The prompt security filter inspects all incoming questions to detect and block indirect prompt injections, jailbreak attempts, and system prompt extraction attacks before query retrieval or generation.",
        "lang": "en",
    },
    {
        "eval_id": "bilingual_legal_compliance",
        "title": "Saudi PDPL Compliance",
        "text": "Enterprise compliance in ArabIQ adheres to the Saudi Personal Data Protection Law (PDPL) ونظام حماية البيانات الشخصية لضمان سيادة البيانات داخل المملكة العربية السعودية وتشفير البيانات في حالة السكون والحركة.",
        "lang": "bi",
    },
    {
        "eval_id": "bilingual_model_eval",
        "title": "Model Evaluation Benchmark",
        "text": "The bilingual evaluation benchmark evaluates Qwen3:8B reasoning and BAAI/bge-m3 dense retrieval across Arabic and English enterprise queries لقياس دقة الاسترجاع والتوليد دون هلاوس.",
        "lang": "bi",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# 15 Smoke Benchmark Cases (5 Arabic, 5 English, 5 Bilingual)
# ──────────────────────────────────────────────────────────────────────────────

SMOKE_CASES = [
    # ── 5 Arabic Cases ──
    {
        "case_id": "AI3-SMOKE-AR-001",
        "language": "ar",
        "category": "legal",
        "query": "ما هي شروط وحساب مكافأة نهاية الخدمة في نظام العمل؟",
        "relevant_chunks": ["labor_law_art84"],
    },
    {
        "case_id": "AI3-SMOKE-AR-002",
        "language": "ar",
        "category": "legal",
        "query": "كم يستحق العامل من مكافأة نهاية الخدمة في حال الاستقالة؟",
        "relevant_chunks": ["labor_law_art85"],
    },
    {
        "case_id": "AI3-SMOKE-AR-003",
        "language": "ar",
        "category": "security",
        "query": "كيف يتم تطبيق نظام التحكم في الوصول وعزل المنظمات في المنصة؟",
        "relevant_chunks": ["sec_policy_rbac"],
    },
    {
        "case_id": "AI3-SMOKE-AR-004",
        "language": "ar",
        "category": "hr",
        "query": "ما هي مدة الإجازة السنوية المستحقة للموظفين في سياسة الموارد البشرية؟",
        "relevant_chunks": ["hr_leave_policy"],
    },
    {
        "case_id": "AI3-SMOKE-AR-005",
        "language": "ar",
        "category": "audit",
        "query": "كيف يعمل سجل التدقيق الأمني ومراقبة المحاولات المشبوهة؟",
        "relevant_chunks": ["sec_policy_audit"],
    },

    # ── 5 English Cases ──
    {
        "case_id": "AI3-SMOKE-EN-001",
        "language": "en",
        "category": "architecture",
        "query": "How does ArabIQ hybrid retrieval combine dense vectors and full-text search?",
        "relevant_chunks": ["arch_hybrid_search"],
    },
    {
        "case_id": "AI3-SMOKE-EN-002",
        "language": "en",
        "category": "architecture",
        "query": "What vector database configuration and distance metric are used for embeddings?",
        "relevant_chunks": ["arch_qdrant_vector"],
    },
    {
        "case_id": "AI3-SMOKE-EN-003",
        "language": "en",
        "category": "infrastructure",
        "query": "What technology stack powers the asynchronous document processing queue?",
        "relevant_chunks": ["cloud_celery_redis"],
    },
    {
        "case_id": "AI3-SMOKE-EN-004",
        "language": "en",
        "category": "database",
        "query": "How does the system prevent worker thread exhaustion during external network calls?",
        "relevant_chunks": ["arch_database_pooling"],
    },
    {
        "case_id": "AI3-SMOKE-EN-005",
        "language": "en",
        "category": "security",
        "query": "How are indirect prompt injection attacks detected and prevented?",
        "relevant_chunks": ["sec_prompt_injection"],
    },

    # ── 5 Bilingual Cases ──
    {
        "case_id": "AI3-SMOKE-BI-001",
        "language": "bilingual",
        "category": "compliance",
        "query": "What are the PDPL requirements ونظام حماية البيانات الشخصية for enterprise data sovereignty?",
        "relevant_chunks": ["bilingual_legal_compliance"],
    },
    {
        "case_id": "AI3-SMOKE-BI-002",
        "language": "bilingual",
        "category": "architecture",
        "query": "Explain Reciprocal Rank Fusion RRF وحساب الترتيب التبادلي k=60 in hybrid search",
        "relevant_chunks": ["arch_hybrid_search"],
    },
    {
        "case_id": "AI3-SMOKE-BI-003",
        "language": "bilingual",
        "category": "evaluation",
        "query": "How does BAAI/bge-m3 evaluate bilingual Arabic and English queries لقياس دقة الاسترجاع؟",
        "relevant_chunks": ["bilingual_model_eval"],
    },
    {
        "case_id": "AI3-SMOKE-BI-004",
        "language": "bilingual",
        "category": "security",
        "query": "Multi-tenant security isolation وعزل المنظمات in Qdrant payload filters",
        "relevant_chunks": ["arch_qdrant_vector", "sec_policy_rbac"],
    },
    {
        "case_id": "AI3-SMOKE-BI-005",
        "language": "bilingual",
        "category": "audit",
        "query": "Audit logging and security tracking لسجلات التدقيق الأمني and cross-tenant attempts",
        "relevant_chunks": ["sec_policy_audit"],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Metric Computation Helper
# ──────────────────────────────────────────────────────────────────────────────

def compute_metrics(retrieved_uuids: List[str], ground_truth_uuids: List[str]) -> Dict[str, float]:
    eval_svc = RetrievalEvaluationService()
    gt_set = set(ground_truth_uuids)

    # Precision
    p3 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    p5 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    p10 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    # Recall
    r3 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    r5 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    r10 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    # MRR
    mrr_val = eval_svc.calculate_mrr(retrieved_uuids, ground_truth_uuids)

    # Hit Rate
    hr3 = 1.0 if any(u in gt_set for u in retrieved_uuids[:3]) else 0.0
    hr5 = 1.0 if any(u in gt_set for u in retrieved_uuids[:5]) else 0.0
    hr10 = 1.0 if any(u in gt_set for u in retrieved_uuids[:10]) else 0.0

    return {
        "p3": p3,
        "p5": p5,
        "p10": p10,
        "r3": r3,
        "r5": r5,
        "r10": r10,
        "mrr": mrr_val,
        "hr3": hr3,
        "hr5": hr5,
        "hr10": hr10,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Benchmark Runner
# ──────────────────────────────────────────────────────────────────────────────

def run_smoke_benchmark():
    print("=" * 70)
    print("AI-3 PRE-BENCHMARK: 15-CASE RETRIEVAL SMOKE BENCHMARK")
    print("=" * 70)

    process = psutil.Process()
    rss_before_mb = process.memory_info().rss / 1024 / 1024
    peak_rss_mb = rss_before_mb

    db = SessionLocal()
    search_service = SearchService(db)
    embedding_svc = EmbeddingService()

    # In-memory Qdrant client for fast, deterministic, self-contained benchmark
    qdrant_client = QdrantClient(":memory:")
    collection_name = "ai3_smoke_benchmark_collection"
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

    test_uid = uuid.uuid4().hex[:8]
    org = Organization(name=f"AI3 Smoke Org {test_uid}", slug=f"ai3-org-{test_uid}")
    db.add(org)
    db.commit()

    eval_to_uuid: Dict[str, str] = {}
    created_chunk_ids = []
    created_pdoc_ids = []
    created_doc_ids = []

    try:
        user = db.query(User).first()
        user_id = user.id if user else 1

        kb = KnowledgeBase(name=f"AI3 Smoke KB {test_uid}", organization_id=org.id, owner_id=user_id)
        db.add(kb)
        db.commit()

        # Seed benchmark chunks into PostgreSQL and in-memory Qdrant
        print(f"[*] Seeding {len(BENCHMARK_CHUNKS)} canonical benchmark chunks...")
        doc = Document(
            filename="ai3_benchmark_corpus.txt",
            storage_path="/benchmark/corpus",
            mime_type="text/plain",
            file_size=5000,
            knowledge_base_id=kb.id,
            created_by=user_id,
            status="Processed",
        )
        db.add(doc)
        db.commit()
        created_doc_ids.append(doc.id)

        pdoc = ParsedDocument(
            document_id=doc.id,
            parsed_text=" ".join(c["text"] for c in BENCHMARK_CHUNKS),
            char_count=sum(len(c["text"]) for c in BENCHMARK_CHUNKS),
            processing_duration=0.5,
        )
        db.add(pdoc)
        db.commit()
        created_pdoc_ids.append(pdoc.id)

        points = []
        for idx, chunk_def in enumerate(BENCHMARK_CHUNKS):
            eval_id = chunk_def["eval_id"]
            text = chunk_def["text"]

            chunk_obj = DocumentChunk(
                parsed_document_id=pdoc.id,
                chunk_index=idx,
                chunk_text=text,
                char_count=len(text),
                estimated_tokens=len(text.split()),
                start_offset=0,
                end_offset=len(text),
                search_vector=func.to_tsvector("simple", text),
            )
            db.add(chunk_obj)
            db.commit()
            created_chunk_ids.append(chunk_obj.id)
            eval_to_uuid[eval_id] = str(chunk_obj.uuid)

            # Generate BGE-M3 embedding for Dense search
            vec = embedding_svc.embed_text(text)
            points.append(
                PointStruct(
                    id=chunk_obj.id,
                    vector=vec,
                    payload={
                        "chunk_uuid": str(chunk_obj.uuid),
                        "parsed_document_id": pdoc.id,
                        "knowledge_base_id": kb.id,
                        "organization_id": org.id,
                        "chunk_index": idx,
                        "text": text,
                        "char_count": len(text),
                        "estimated_tokens": len(text.split()),
                    },
                )
            )

        qdrant_client.upsert(collection_name=collection_name, points=points)
        print(f"[OK] Successfully indexed {len(points)} vectors and FTS documents.")

        # Execute Benchmark across the 3 modes
        modes = ["dense", "keyword", "hybrid"]
        results_by_mode: Dict[str, Any] = {}

        # Patch QdrantService to use our benchmark in-memory client
        with patch.object(QdrantService, "_client", qdrant_client), \
             patch.object(search_service.qdrant_service, "collection_name", collection_name):

            for mode in modes:
                print(f"\n--- Running Evaluation: Mode = {mode.upper()} ---")
                case_metrics: List[Dict[str, float]] = []
                timing_records: List[Dict[str, float]] = []

                for case in SMOKE_CASES:
                    query = case["query"]
                    relevant_eval_ids = case["relevant_chunks"]
                    gt_uuids = [eval_to_uuid[eid] for eid in relevant_eval_ids if eid in eval_to_uuid]

                    profiler = RetrievalProfiler()
                    t_start = time.perf_counter()

                    if mode == "dense":
                        # Pure dense vector search
                        search_results = search_service._dense_search(
                            query=query,
                            knowledge_base_id=kb.id,
                            organization_id=org.id,
                            top_k=10,
                            profiler=profiler,
                        )
                    elif mode == "keyword":
                        # Pure PostgreSQL FTS keyword search
                        profiler.start("keyword_search")
                        search_results = search_service.keyword_search(
                            query=query,
                            knowledge_base_id=kb.id,
                            organization_id=org.id,
                            top_k=10,
                        )
                        profiler.stop("keyword_search")
                    elif mode == "hybrid":
                        # Hybrid search (Dense + Keyword + RRF)
                        search_results = search_service.hybrid_search(
                            query=query,
                            knowledge_base_id=kb.id,
                            organization_id=org.id,
                            top_k=10,
                            profiler=profiler,
                        )

                    total_elapsed_ms = (time.perf_counter() - t_start) * 1000

                    # Check peak RSS
                    current_rss = process.memory_info().rss / 1024 / 1024
                    if current_rss > peak_rss_mb:
                        peak_rss_mb = current_rss

                    retrieved_uuids = [r.chunk_uuid for r in search_results]
                    m = compute_metrics(retrieved_uuids, gt_uuids)
                    case_metrics.append(m)

                    timing_records.append({
                        "embedding_ms": profiler.metrics.embedding_ms,
                        "dense_search_ms": profiler.metrics.dense_search_ms,
                        "keyword_search_ms": profiler.metrics.keyword_search_ms,
                        "fusion_ms": profiler.metrics.fusion_ms,
                        "total_ms": total_elapsed_ms,
                    })

                # Aggregate metrics for this mode
                avg_m = {
                    k: float(np.mean([cm[k] for cm in case_metrics]))
                    for k in case_metrics[0].keys()
                }

                totals = [t["total_ms"] for t in timing_records]
                timing_summary = {
                    "min_ms": float(np.min(totals)),
                    "p50_ms": float(np.percentile(totals, 50)),
                    "p95_ms": float(np.percentile(totals, 95)),
                    "max_ms": float(np.max(totals)),
                    "avg_embedding_ms": float(np.mean([t["embedding_ms"] for t in timing_records])),
                    "avg_dense_ms": float(np.mean([t["dense_search_ms"] for t in timing_records])),
                    "avg_keyword_ms": float(np.mean([t["keyword_search_ms"] for t in timing_records])),
                    "avg_fusion_ms": float(np.mean([t["fusion_ms"] for t in timing_records])),
                }

                results_by_mode[mode] = {
                    "metrics": avg_m,
                    "timings": timing_summary,
                }

                print(f"  * Recall@3: {avg_m['r3']*100:.1f}% | Recall@5: {avg_m['r5']*100:.1f}% | Recall@10: {avg_m['r10']*100:.1f}%")
                print(f"  * Precision@3: {avg_m['p3']*100:.1f}% | Precision@5: {avg_m['p5']*100:.1f}% | Precision@10: {avg_m['p10']*100:.1f}%")
                print(f"  * MRR: {avg_m['mrr']:.3f} | HitRate@5: {avg_m['hr5']*100:.1f}%")
                print(f"  * Latency (ms): min={timing_summary['min_ms']:.1f}, p50={timing_summary['p50_ms']:.1f}, p95={timing_summary['p95_ms']:.1f}, max={timing_summary['max_ms']:.1f}")

        rss_after_mb = process.memory_info().rss / 1024 / 1024

        benchmark_report = {
            "cases_count": len(SMOKE_CASES),
            "distribution": {"arabic": 5, "english": 5, "bilingual": 5},
            "results_by_mode": results_by_mode,
            "resource_usage": {
                "rss_before_mb": rss_before_mb,
                "peak_rss_mb": peak_rss_mb,
                "rss_after_mb": rss_after_mb,
            },
        }

        output_path = os.path.join(os.path.dirname(__file__), "..", "ai3_smoke_benchmark_results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_report, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] Results successfully written to {output_path}")

        return benchmark_report

    finally:
        # Strict database cleanup
        if created_chunk_ids:
            db.query(DocumentChunk).filter(DocumentChunk.id.in_(created_chunk_ids)).delete(synchronize_session=False)
        if created_pdoc_ids:
            db.query(ParsedDocument).filter(ParsedDocument.id.in_(created_pdoc_ids)).delete(synchronize_session=False)
        if created_doc_ids:
            db.query(Document).filter(Document.id.in_(created_doc_ids)).delete(synchronize_session=False)
        db.query(KnowledgeBase).filter(KnowledgeBase.organization_id == org.id).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id == org.id).delete(synchronize_session=False)
        db.commit()
        db.close()


if __name__ == "__main__":
    run_smoke_benchmark()
