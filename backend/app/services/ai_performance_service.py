"""
AIPerformanceService & RetrievalEvaluationService — Refinement #3:
Retrieval Quality Evaluation (Precision@K, Recall@K, MRR, NDCG, Hit Rate)
and Retrieval Error Classification Engine.
"""

import math
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

logger = logging.getLogger("app.services.ai_performance_service")


class RetrievalEvaluationService:
    @staticmethod
    def calculate_precision_at_k(retrieved_ids: List[str], ground_truth_ids: List[str], k: int = 5) -> float:
        top_k = retrieved_ids[:k]
        if not top_k:
            return 0.0
        relevant = set(top_k).intersection(set(ground_truth_ids))
        return len(relevant) / float(k)

    @staticmethod
    def calculate_recall_at_k(retrieved_ids: List[str], ground_truth_ids: List[str], k: int = 5) -> float:
        if not ground_truth_ids:
            return 0.0
        top_k = retrieved_ids[:k]
        relevant = set(top_k).intersection(set(ground_truth_ids))
        return len(relevant) / float(len(ground_truth_ids))

    @staticmethod
    def calculate_mrr(retrieved_ids: List[str], ground_truth_ids: List[str]) -> float:
        gt_set = set(ground_truth_ids)
        for idx, item in enumerate(retrieved_ids):
            if item in gt_set:
                return 1.0 / (idx + 1)
        return 0.0

    @staticmethod
    def calculate_ndcg_at_k(retrieved_ids: List[str], ground_truth_ids: List[str], k: int = 5) -> float:
        top_k = retrieved_ids[:k]
        gt_set = set(ground_truth_ids)

        dcg = 0.0
        for i, doc_id in enumerate(top_k):
            rel = 1.0 if doc_id in gt_set else 0.0
            dcg += rel / math.log2(i + 2)

        idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gt_set), k)))
        return (dcg / idcg) if idcg > 0 else 0.0

    @classmethod
    def classify_retrieval_error(
        self,
        retrieved_ids: List[str],
        ground_truth_ids: List[str],
        avg_score: float,
    ) -> Optional[str]:
        """
        Refinement #3: Classifies retrieval failures into distinct operational buckets:
        - No Retrieval
        - Wrong Retrieval
        - Partial Retrieval
        - Low Confidence Retrieval
        """
        if not retrieved_ids:
            return "No Retrieval"

        gt_set = set(ground_truth_ids)
        retrieved_set = set(retrieved_ids)
        overlap = retrieved_set.intersection(gt_set)

        if not overlap:
            return "Wrong Retrieval"
        elif len(overlap) < len(gt_set):
            return "Partial Retrieval"
        elif avg_score < 0.40:
            return "Low Confidence Retrieval"

        return None


class AIPerformanceService:
    def __init__(self, db: Session):
        self.db = db
        self.retrieval_eval = RetrievalEvaluationService()

    def evaluate_retrieval_batch(self, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        p_5_list, r_5_list, mrr_list, ndcg_list = [], [], [], []
        error_counts: Dict[str, int] = {}

        for case in test_cases:
            retrieved = case.get("retrieved_ids", [])
            ground_truth = case.get("ground_truth_ids", [])
            avg_score = case.get("avg_score", 0.80)

            p_5 = self.retrieval_eval.calculate_precision_at_k(retrieved, ground_truth, k=5)
            r_5 = self.retrieval_eval.calculate_recall_at_k(retrieved, ground_truth, k=5)
            mrr = self.retrieval_eval.calculate_mrr(retrieved, ground_truth)
            ndcg = self.retrieval_eval.calculate_ndcg_at_k(retrieved, ground_truth, k=5)

            p_5_list.append(p_5)
            r_5_list.append(r_5)
            mrr_list.append(mrr)
            ndcg_list.append(ndcg)

            err = self.retrieval_eval.classify_retrieval_error(retrieved, ground_truth, avg_score)
            if err:
                error_counts[err] = error_counts.get(err, 0) + 1

        total = len(test_cases) or 1
        return {
            "precision_at_5": sum(p_5_list) / total,
            "recall_at_5": sum(r_5_list) / total,
            "mrr": sum(mrr_list) / total,
            "ndcg_at_5": sum(ndcg_list) / total,
            "hit_rate": len([p for p in p_5_list if p > 0]) / float(total),
            "error_classification": error_counts,
        }
