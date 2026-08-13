import sys
import os
import math
import logging
from typing import List, Dict, Set

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.session import SessionLocal
from app.services.search_service import SearchService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("retrieval_benchmark")

# ──────────────────────────────────────────────────────────────────────────────
# Metric Calculations
# ──────────────────────────────────────────────────────────────────────────────

def precision_at_k(retrieved_uuids: List[str], relevant_uuids: Set[str], k: int) -> float:
    top_k = retrieved_uuids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for uuid in top_k if uuid in relevant_uuids)
    return hits / k


def recall_at_k(retrieved_uuids: List[str], relevant_uuids: Set[str], k: int) -> float:
    if not relevant_uuids:
        return 1.0
    top_k = retrieved_uuids[:k]
    hits = sum(1 for uuid in top_k if uuid in relevant_uuids)
    return hits / len(relevant_uuids)


def mrr(retrieved_uuids: List[str], relevant_uuids: Set[str]) -> float:
    for rank, uuid in enumerate(retrieved_uuids, start=1):
        if uuid in relevant_uuids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_uuids: List[str], relevant_uuids: Set[str], k: int) -> float:
    top_k = retrieved_uuids[:k]
    dcg = 0.0
    for i, uuid in enumerate(top_k, start=1):
        rel = 1.0 if uuid in relevant_uuids else 0.0
        dcg += rel / math.log2(i + 1)

    ideal_hits = min(len(relevant_uuids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))

    return (dcg / idcg) if idcg > 0 else 0.0


def citation_accuracy(retrieved_uuids: List[str], relevant_uuids: Set[str]) -> float:
    if not retrieved_uuids:
        return 0.0
    top1 = retrieved_uuids[0]
    return 1.0 if top1 in relevant_uuids else 0.0

# ──────────────────────────────────────────────────────────────────────────────
# Evaluation Harness
# ──────────────────────────────────────────────────────────────────────────────

def run_retrieval_benchmark():
    logger.info("==================================================")
    logger.info("STARTING RETRIEVAL QUALITY BENCHMARK HARNESS")
    logger.info("==================================================")

    db = SessionLocal()
    search_service = SearchService(db)

    try:
        # Benchmark evaluation suite with sample queries and gold chunk matching patterns
        eval_dataset: List[Dict] = [
            {
                "query": "ArabIQ platform architecture and components",
                "lang": "EN",
                "kb_id": 1,
                "keywords": ["FastAPI", "Qdrant", "PostgreSQL", "RRF", "BAAI/bge-m3"],
            },
            {
                "query": "ما هي المكونات التقنية لمنصة عرب آي كيو؟",
                "lang": "AR",
                "kb_id": 1,
                "keywords": ["منصة", "ذكاء", "المؤسسات", "Qdrant", "PostgreSQL"],
            },
            {
                "query": "Hybrid dense and keyword search fusion",
                "lang": "EN",
                "kb_id": 1,
                "keywords": ["hybrid", "dense", "keyword", "reciprocal", "rank"],
            },
            {
                "query": "دمج البحث الدلالي والبحث بالكلمات المفتاحية",
                "lang": "AR",
                "kb_id": 1,
                "keywords": ["الدمج", "الترتيبي", "التبادلي", "RRF", "الهجين"],
            },
        ]

        p5_scores = []
        r5_scores = []
        mrr_scores = []
        ndcg10_scores = []
        citation_scores = []

        logger.info(f"Evaluating {len(eval_dataset)} benchmark queries...")

        for idx, sample in enumerate(eval_dataset, start=1):
            query = sample["query"]
            kb_id = sample["kb_id"]
            keywords = sample["keywords"]

            # Perform Hybrid Search
            results = search_service.hybrid_search(
                query=query,
                knowledge_base_id=kb_id,
                top_k=10,
            )

            retrieved_uuids = [r.chunk_uuid for r in results]
            
            # Ground-truth relevancy: match chunks containing any required keywords
            relevant_uuids = set()
            for r in results:
                text_lower = r.text.lower()
                if any(kw.lower() in text_lower for kw in keywords):
                    relevant_uuids.add(r.chunk_uuid)

            # Calculate metrics
            p5 = precision_at_k(retrieved_uuids, relevant_uuids, k=5)
            r5 = recall_at_k(retrieved_uuids, relevant_uuids, k=5)
            mrr_val = mrr(retrieved_uuids, relevant_uuids)
            ndcg10 = ndcg_at_k(retrieved_uuids, relevant_uuids, k=10)
            cite_acc = citation_accuracy(retrieved_uuids, relevant_uuids)

            p5_scores.append(p5)
            r5_scores.append(r5)
            mrr_scores.append(mrr_val)
            ndcg10_scores.append(ndcg10)
            citation_scores.append(cite_acc)

            logger.info(f"  Query [{idx}/{len(eval_dataset)}] ({sample['lang']}): '{query[:35]}...'")
            logger.info(f"    • P@5: {p5:.2f} | R@5: {r5:.2f} | MRR: {mrr_val:.2f} | NDCG@10: {ndcg10:.2f} | Citation: {cite_acc:.2f}")

        # Compute benchmark averages
        avg_p5 = sum(p5_scores) / len(p5_scores) if p5_scores else 0.0
        avg_r5 = sum(r5_scores) / len(r5_scores) if r5_scores else 0.0
        avg_mrr = sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0.0
        avg_ndcg10 = sum(ndcg10_scores) / len(ndcg10_scores) if ndcg10_scores else 0.0
        avg_cite = sum(citation_scores) / len(citation_scores) if citation_scores else 0.0

        logger.info("\n==================================================")
        logger.info("RETRIEVAL QUALITY BENCHMARK BASELINE REPORT")
        logger.info("==================================================")
        logger.info(f"  • Precision@5       : {avg_p5 * 100:.1f}%")
        logger.info(f"  • Recall@5          : {avg_r5 * 100:.1f}%")
        logger.info(f"  • MRR               : {avg_mrr:.3f}")
        logger.info(f"  • NDCG@10           : {avg_ndcg10:.3f}")
        logger.info(f"  • Citation Accuracy : {avg_cite * 100:.1f}%")
        logger.info("==================================================")

        return {
            "p5": avg_p5,
            "r5": avg_r5,
            "mrr": avg_mrr,
            "ndcg10": avg_ndcg10,
            "citation_accuracy": avg_cite,
        }

    finally:
        db.close()

if __name__ == "__main__":
    run_retrieval_benchmark()
