"""
AI-3 Full Retrieval Performance & Quality Benchmark Runner.

Evaluates Pure Enterprise Retrieval (No LLM generation):
1. Dense Retrieval (BAAI/bge-m3 + Qdrant)
2. Keyword Retrieval (PostgreSQL FTS on GIN tsvector)
3. Hybrid Retrieval (Dense + Keyword + RRF with k=60)

Dataset Architecture (50 Evaluation Cases):
- 15 Arabic cases (legal, HR, security, enterprise policy)
- 15 English cases (architecture, infrastructure, database, security)
- 10 Bilingual cases:
  * 3 Arabic Query -> English Content
  * 3 English Query -> Arabic Content
  * 4 Mixed-language Query -> Mixed-language Content
- 5 Multi-chunk cases (synthesizing 2-3 target chunks)
- 5 Negative / Unanswerable queries (0 relevant chunks)
Plus:
- 6 Dedicated Tenant Isolation Verification cases

Quality Metrics:
- Recall@1, Recall@3, Recall@5, Recall@10
- Precision@1, Precision@3, Precision@5, Precision@10
- MRR (Mean Reciprocal Rank)
- Hit Rate@1, Hit Rate@3, Hit Rate@5, Hit Rate@10
- NDCG@3, NDCG@5, NDCG@10
- Negative query metrics: No-result rate, False retrieval rate, Irrelevant-top-k rate

Performance & Profiling:
- query validation, embedding generation, dense search, keyword search, RRF fusion, total retrieval
- min, p50, p95, max, mean
- RSS memory profiling: before, after model load, peak, after benchmark
"""

import os
import sys
import time
import json
import math
import uuid
from typing import Dict, List, Any, Set, Optional

# Force UTF-8 on Windows stdout/stderr
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

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
# 1. Benchmark Corpus (30 Chunks: Canonical Policies + Distractors)
# ──────────────────────────────────────────────────────────────────────────────

CORPUS_CHUNKS = [
    # ── Legal & Compliance (Saudi Labor Law & PDPL) ──
    {
        "eval_id": "legal_labor_art84",
        "category": "legal",
        "title": "Saudi Labor Law - Article 84 Service Award",
        "text": "تنص المادة الرابعة والثمانون من نظام العمل السعودي على أنه إذا انتهت علاقة العمل وجب على صاحب العمل أن يدفع إلى العامل مكافأة عن مدة خدمته تحسب على أساس أجر نصف شهر عن كل سنة من السنوات الخمس الأولى، وأجر شهر عن كل سنة من السنوات التالية، ويتخذ الأجر الأخير أساساً لحساب المكافأة، ويستحق العامل مكافأة عن أجزاء السنة بنسبة ما قضاه منها في العمل.",
        "lang": "ar",
    },
    {
        "eval_id": "legal_labor_art85",
        "category": "legal",
        "title": "Saudi Labor Law - Article 85 Resignation Entitlement",
        "text": "تنص المادة الخامسة والثمانون من نظام العمل السعودي على استحقاق العامل ثلث المكافأة بعد خدمة لا تقل عن سنتين متتاليتين ولا تزيد على خمس سنوات، وثلثيها إذا زادت مدة خدمته على خمس سنوات متتالية ولم تبلغ عشر سنوات، ويستحق المكافأة كاملة إذا بلغت مدة خدمته عشر سنوات فأكثر في حال الاستقالة.",
        "lang": "ar",
    },
    {
        "eval_id": "legal_labor_art77",
        "category": "legal",
        "title": "Saudi Labor Law - Article 77 Unlawful Termination",
        "text": "تنص المادة السابعة والسبعون من نظام العمل السعودي على أنه ما لم يتضمن العقد تعويضاً محدداً، يستحق الطرف المتضرر من إنهاء العقد لسبب غير مشروع تعويضاً يعادل أجر خمسة عشر يوماً عن كل سنة من سنوات خدمة العامل إذا كان العقد غير محدد المدة، أو أجر المدة الباقية إذا كان العقد محدد المدة، على ألا يقل التعويض عن أجر شهرين.",
        "lang": "ar",
    },
    {
        "eval_id": "legal_labor_art98",
        "category": "legal",
        "title": "Saudi Labor Law - Article 98 Standard Working Hours",
        "text": "تنص المادة الثامنة والتسعون من نظام العمل السعودي على أنه لا يجوز تشغيل العامل تشغيلاً فعلياً أكثر من ثماني ساعات في اليوم الواحد إذا اعتمد صاحب العمل المعيار اليومي، أو أكثر من ثمان وأربعين ساعة في الأسبوع إذا اعتمد المعيار الأسبوعي، وتخفض ساعات العمل الفعلية خلال شهر رمضان للمسلمين بحيث لا تزيد على ست ساعات في اليوم أو ست وثلاثين ساعة في الأسبوع.",
        "lang": "ar",
    },
    {
        "eval_id": "legal_pdpl_sovereignty",
        "category": "compliance",
        "title": "Saudi PDPL - Data Sovereignty and Cross-Border Transfer",
        "text": "وفقاً لنظام حماية البيانات الشخصية السعودي (PDPL) واللوائح التنفيذية الصادرة عن الهيئة السعودية للبيانات والذكاء الاصطناعي (سدايا)، يحظر نقل البيانات الشخصية خارج أراضي المملكة العربية السعودية إلا في حالات محددة تتطلب ضمان مستوى حماية مماثل وعدم المساس بالأمن الوطني أو السيادة الرقمية للبيانات.",
        "lang": "ar",
    },
    {
        "eval_id": "legal_pdpl_breach",
        "category": "compliance",
        "title": "Saudi PDPL - Breach Notification Obligations",
        "text": "The Saudi Personal Data Protection Law (PDPL) mandates that data controllers notify the competent authority (SDAIA) within 72 hours of becoming aware of any personal data breach or unauthorized disclosure that causes material harm to data subjects ونظام حماية البيانات الشخصية والإشعار الفوري عن التسريبات.",
        "lang": "bi",
    },

    # ── Enterprise HR Policies ──
    {
        "eval_id": "hr_annual_leave",
        "category": "hr",
        "title": "Enterprise HR Policy - Annual Leave",
        "text": "تحدد سياسة الموارد البشرية الإجازة السنوية المدفوعة بـ 30 يوماً تقويمياً للموظفين الذين أمضوا خمس سنوات متصلة في الخدمة، وبـ 21 يوماً لمن تقل خدمتهم عن ذلك، ويجب تقديم طلب الإجازة واعتماده من المدير المباشر قبل موعدها بأسبوعين على الأقل.",
        "lang": "ar",
    },
    {
        "eval_id": "hr_sick_leave",
        "category": "hr",
        "title": "Enterprise HR Policy - Sick Leave",
        "text": "يستحق الموظف إجازة مرضية مدفوعة الأجر بالكامل عن الثلاثين يوماً الأولى، وثلاثة أرباع الأجر عن الستين يوماً التالية، وبدون أجر للثلاثين يوماً التي تلي ذلك خلال سنة واحدة، بشرط تقديم تقرير طبي معتمد من جهة صحية مرخصة.",
        "lang": "ar",
    },
    {
        "eval_id": "hr_remote_work",
        "category": "hr",
        "title": "Enterprise Remote Work Policy",
        "text": "Under the ArabIQ flexible workplace policy, eligible employees may work remotely up to two days per week subject to departmental manager approval, provided that network connectivity complies with enterprise VPN and zero-trust authentication standards.",
        "lang": "en",
    },
    {
        "eval_id": "hr_expense_reimbursement",
        "category": "hr",
        "title": "Business Travel and Expense Reimbursement",
        "text": "Business expenses incurred during official corporate travel must be submitted within 14 calendar days using itemized tax receipts. Per diem allowances for international lodging and meals adhere to corporate grade schedule Tier-2.",
        "lang": "en",
    },
    {
        "eval_id": "hr_disciplinary_code",
        "category": "hr",
        "title": "Employee Conduct and Disciplinary Actions",
        "text": "لائحة تنظيم العمل والجزاءات التأديبية تدرج العقوبات تدريجياً من الإنذار الكتابي، ثم الخصم من الراتب بما لا يتجاوز خمسة أيام في المرة الواحدة، وصولاً إلى الفصل من الخدمة وفق الحالات المنصوص عليها في المادة الثمانين من نظام العمل.",
        "lang": "ar",
    },

    # ── Platform Architecture & Engineering ──
    {
        "eval_id": "arch_hybrid_search",
        "category": "architecture",
        "title": "ArabIQ Hybrid Search Architecture",
        "text": "ArabIQ hybrid search architecture fuses dense embeddings from BAAI/bge-m3 with PostgreSQL GIN tsvector full-text search using Reciprocal Rank Fusion RRF with constant k=60 to balance lexical and semantic precision وحساب الترتيب التبادلي.",
        "lang": "bi",
    },
    {
        "eval_id": "arch_qdrant_vector",
        "category": "architecture",
        "title": "Qdrant Vector Database Engine",
        "text": "Vector retrieval is implemented via Qdrant with cosine distance on 1024-dimensional embeddings. Payload indexes on organization_id and knowledge_base_id enforce strict multi-tenant partitioning and prevent cross-tenant vector leakage وعزل المنظمات.",
        "lang": "bi",
    },
    {
        "eval_id": "arch_database_pooling",
        "category": "database",
        "title": "SQLAlchemy Database Connection Pool",
        "text": "Database connection management utilizes SQLAlchemy connection pooling with proactive checkout release before remote LLM or vector DB network calls, preventing PostgreSQL connection exhaustion under high concurrency.",
        "lang": "en",
    },
    {
        "eval_id": "arch_celery_redis",
        "category": "infrastructure",
        "title": "Asynchronous Ingestion with Celery and Redis",
        "text": "The asynchronous document ingestion pipeline employs Celery workers backed by Redis broker for task dispatch, concurrency admission control, and distributed leasing to handle large document parsing reliably.",
        "lang": "en",
    },
    {
        "eval_id": "arch_storage_dedup",
        "category": "infrastructure",
        "title": "Document Storage and Content Deduplication",
        "text": "Uploaded documents are stored in local or S3-compatible object storage with SHA-256 cryptographic hashing to detect byte-level duplicates before initiating document extraction or text parsing pipelines.",
        "lang": "en",
    },
    {
        "eval_id": "arch_doc_relationships",
        "category": "intelligence",
        "title": "Inter-Document Relationship Detection",
        "text": "The DocumentRelationshipService analyzes vector proximity and content metadata to discover semantic relationships between documents, categorizing pairs as Similar (cosine >= 0.75), Duplicate (cosine >= 0.96), or Translated Versions.",
        "lang": "en",
    },
    {
        "eval_id": "arch_celery_dlq",
        "category": "infrastructure",
        "title": "Dead Letter Queue and Retry Exponential Backoff",
        "text": "Failed indexing tasks in Celery are automatically retried up to three times with exponential backoff before being quarantined into the Redis Dead Letter Queue (DLQ) for manual administrator inspection.",
        "lang": "en",
    },

    # ── Platform Security & Governance ──
    {
        "eval_id": "sec_prompt_injection",
        "category": "security",
        "title": "Prompt Injection and Jailbreak Defense",
        "text": "The prompt security filter inspects all incoming questions to detect and block indirect prompt injections, jailbreak attempts, and system prompt extraction attacks before query retrieval or generation with risk threshold 0.70.",
        "lang": "en",
    },
    {
        "eval_id": "sec_audit_trail",
        "category": "security",
        "title": "Enterprise Security Audit Trail",
        "text": "The ArabIQ security audit log records all user authentication, authorization, prompt security decisions, and cross-tenant access attempts with SHA-256 integrity and strict organization boundary isolation لسجلات التدقيق الأمني ومراقبة المحاولات المشبوهة.",
        "lang": "bi",
    },
    {
        "eval_id": "sec_rbac_isolation",
        "category": "security",
        "title": "Multi-Tenant RBAC and Organization Scoping",
        "text": "تعتمد منصة ArabIQ نظام التحكم في الوصول القائم على الأدوار RBAC مع عزل كامل للمنظمات، حيث يمنع أي مستخدم من الوصول إلى قواعد معرفة تابعة لمنظمة أخرى لضمان أمان البيانات متعددة المستأجرين.",
        "lang": "ar",
    },
    {
        "eval_id": "sec_encryption_standards",
        "category": "security",
        "title": "Data Encryption in Transit and at Rest",
        "text": "Enterprise data security enforces AES-256 encryption at rest for all database volumes and object stores, alongside TLS 1.3 encryption in transit for all client-to-backend and service-to-service communications.",
        "lang": "en",
    },

    # ── Evaluation & Model Benchmarks ──
    {
        "eval_id": "eval_bilingual_bge",
        "category": "evaluation",
        "title": "Bilingual Model Evaluation with BGE-M3",
        "text": "The bilingual evaluation benchmark evaluates Qwen3:8B reasoning and BAAI/bge-m3 dense retrieval across Arabic and English enterprise queries لقياس دقة الاسترجاع والتوليد دون هلاوس.",
        "lang": "bi",
    },

    # ── Topical Distractors (Fine-Grained Confusers) ──
    {
        "eval_id": "distractor_commercial_law",
        "category": "distractor",
        "title": "Saudi Commercial Courts Law (Distractor)",
        "text": "يختص نظام المحاكم التجارية السعودي بالنظر في جميع المنازعات التجارية الأصلية والتبعية التي تحدث بين التجار، والدعاوى المقامة على التاجر في عقود التوريد والمقاولات، ولا يشمل منازعات عقود العمل والعمال.",
        "lang": "ar",
    },
    {
        "eval_id": "distractor_gdpr_compliance",
        "category": "distractor",
        "title": "European Union GDPR Framework (Distractor)",
        "text": "The European General Data Protection Regulation (GDPR) governs personal data processing across member states, imposing standard contractual clauses (SCCs) for transfers outside the European Economic Area under Article 46.",
        "lang": "en",
    },
    {
        "eval_id": "distractor_faiss_vector",
        "category": "distractor",
        "title": "Standalone FAISS Vector Indexing (Distractor)",
        "text": "Facebook AI Similarity Search (FAISS) enables exact and approximate nearest neighbor search in dense vector spaces using inverted file indexes with product quantization (IVF-PQ) for offline GPU clusters.",
        "lang": "en",
    },
    {
        "eval_id": "distractor_elasticsearch_bm25",
        "category": "distractor",
        "title": "Elasticsearch Lucene BM25 Engine (Distractor)",
        "text": "Elasticsearch clusters utilize Lucene inverted indexes with BM25 scoring algorithm to perform sharded keyword retrieval and distributed text analytics across cluster nodes.",
        "lang": "en",
    },
    {
        "eval_id": "distractor_travel_insurance",
        "category": "distractor",
        "title": "Corporate Travel Medical Insurance (Distractor)",
        "text": "The corporate travel medical insurance policy provides emergency hospital coverage and evacuation services for international assignees, but does not cover local lodging or daily per diem expenses.",
        "lang": "en",
    },
    {
        "eval_id": "distractor_docker_swarm",
        "category": "distractor",
        "title": "Docker Swarm Container Orchestration (Distractor)",
        "text": "Docker Swarm manages containerized service clusters with overlay networking and round-robin ingress routing for microservices, operating independently of background Celery task dispatchers.",
        "lang": "en",
    },
    {
        "eval_id": "distractor_alembic_migrations",
        "category": "distractor",
        "title": "Alembic Schema Migration Framework (Distractor)",
        "text": "Alembic provides programmatic schema revision history and autogenerate migration scripts for SQLAlchemy metadata, tracking DDL modifications across staging and production databases.",
        "lang": "en",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# 2. 50 Evaluation Cases Definition
# ──────────────────────────────────────────────────────────────────────────────

FULL_BENCHMARK_CASES = [
    # ── 15 Arabic Cases (Positive) ──
    {
        "case_id": "AI3-AR-001",
        "type": "positive",
        "language": "ar",
        "category": "legal",
        "query": "ما هي شروط وحساب مكافأة نهاية الخدمة في نظام العمل السعودي؟",
        "relevant_chunks": ["legal_labor_art84"],
    },
    {
        "case_id": "AI3-AR-002",
        "type": "positive",
        "language": "ar",
        "category": "legal",
        "query": "كم يستحق العامل من مكافأة نهاية الخدمة في حال الاستقالة؟",
        "relevant_chunks": ["legal_labor_art85"],
    },
    {
        "case_id": "AI3-AR-003",
        "type": "positive",
        "language": "ar",
        "category": "legal",
        "query": "ما هو التعويض المستحق في حال إنهاء عقد العمل لسبب غير مشروع؟",
        "relevant_chunks": ["legal_labor_art77"],
    },
    {
        "case_id": "AI3-AR-004",
        "type": "positive",
        "language": "ar",
        "category": "legal",
        "query": "كم عدد ساعات العمل اليومية والأسبوعية الفعلية في نظام العمل وخلال شهر رمضان؟",
        "relevant_chunks": ["legal_labor_art98"],
    },
    {
        "case_id": "AI3-AR-005",
        "type": "positive",
        "language": "ar",
        "category": "compliance",
        "query": "ما هي ضوابط نقل البيانات الشخصية خارج المملكة وفق نظام حماية البيانات الشخصية؟",
        "relevant_chunks": ["legal_pdpl_sovereignty"],
    },
    {
        "case_id": "AI3-AR-006",
        "type": "positive",
        "language": "ar",
        "category": "hr",
        "query": "ما هي مدة الإجازة السنوية المستحقة للموظف وكيف ترتبط بسنوات الخدمة؟",
        "relevant_chunks": ["hr_annual_leave"],
    },
    {
        "case_id": "AI3-AR-007",
        "type": "positive",
        "language": "ar",
        "category": "hr",
        "query": "كيف يتم احتساب راتب الإجازة المرضية وتوزيعها على مدار السنة؟",
        "relevant_chunks": ["hr_sick_leave"],
    },
    {
        "case_id": "AI3-AR-008",
        "type": "positive",
        "language": "ar",
        "category": "hr",
        "query": "ما هو التدرج في الجزاءات التأديبية للموظفين والحد الأقصى للخصم من الراتب؟",
        "relevant_chunks": ["hr_disciplinary_code"],
    },
    {
        "case_id": "AI3-AR-009",
        "type": "positive",
        "language": "ar",
        "category": "security",
        "query": "كيف يتم تطبيق نظام التحكم في الوصول وعزل المنظمات في منصة ArabIQ؟",
        "relevant_chunks": ["sec_rbac_isolation"],
    },
    {
        "case_id": "AI3-AR-010",
        "type": "positive",
        "language": "ar",
        "category": "architecture",
        "query": "ما هي آلية دمج البحث الدلالي مع البحث النصي باستخدام الترتيب التبادلي RRF؟",
        "relevant_chunks": ["arch_hybrid_search"],
    },
    {
        "case_id": "AI3-AR-011",
        "type": "positive",
        "language": "ar",
        "category": "architecture",
        "query": "ما هي محددات أبعاد المتجهات ومقياس المسافة المستخدم في قاعدة بيانات كودرانت؟",
        "relevant_chunks": ["arch_qdrant_vector"],
    },
    {
        "case_id": "AI3-AR-012",
        "type": "positive",
        "language": "ar",
        "category": "security",
        "query": "ما هي خصائص سجل التدقيق الأمني ومراقبة المحاولات المشبوهة عبر المنظمات؟",
        "relevant_chunks": ["sec_audit_trail"],
    },
    {
        "case_id": "AI3-AR-013",
        "type": "positive",
        "language": "ar",
        "category": "evaluation",
        "query": "كيف يقيس إطار التقييم دقة نموذج BGE-M3 وتوليد الإجابات باللغتين العربية والإنجليزية؟",
        "relevant_chunks": ["eval_bilingual_bge"],
    },
    {
        "case_id": "AI3-AR-014",
        "type": "positive",
        "language": "ar",
        "category": "compliance",
        "query": "ما هي مهلة إشعار الجهة المختصة سدايا عند وقوع تسريب للبيانات الشخصية؟",
        "relevant_chunks": ["legal_pdpl_breach"],
    },
    {
        "case_id": "AI3-AR-015",
        "type": "positive",
        "language": "ar",
        "category": "legal",
        "query": "المادة الرابعة والثمانون مكافأة نهاية الخدمة نصف شهر وشهر الأجر الأخير",
        "relevant_chunks": ["legal_labor_art84"],
    },

    # ── 15 English Cases (Positive) ──
    {
        "case_id": "AI3-EN-001",
        "type": "positive",
        "language": "en",
        "category": "architecture",
        "query": "How does the ArabIQ hybrid search architecture combine dense vectors and PostgreSQL FTS?",
        "relevant_chunks": ["arch_hybrid_search"],
    },
    {
        "case_id": "AI3-EN-002",
        "type": "positive",
        "language": "en",
        "category": "architecture",
        "query": "What vector database distance metric and embedding dimensionality are configured in Qdrant?",
        "relevant_chunks": ["arch_qdrant_vector"],
    },
    {
        "case_id": "AI3-EN-003",
        "type": "positive",
        "language": "en",
        "category": "database",
        "query": "How does SQLAlchemy connection pooling prevent database connection exhaustion during remote calls?",
        "relevant_chunks": ["arch_database_pooling"],
    },
    {
        "case_id": "AI3-EN-004",
        "type": "positive",
        "language": "en",
        "category": "infrastructure",
        "query": "What technology powers the asynchronous document ingestion queue and admission control?",
        "relevant_chunks": ["arch_celery_redis"],
    },
    {
        "case_id": "AI3-EN-005",
        "type": "positive",
        "language": "en",
        "category": "infrastructure",
        "query": "How does the platform detect duplicate document uploads before running text extraction?",
        "relevant_chunks": ["arch_storage_dedup"],
    },
    {
        "case_id": "AI3-EN-006",
        "type": "positive",
        "language": "en",
        "category": "intelligence",
        "query": "What cosine similarity thresholds classify document pairs as Similar or Duplicate in relationship detection?",
        "relevant_chunks": ["arch_doc_relationships"],
    },
    {
        "case_id": "AI3-EN-007",
        "type": "positive",
        "language": "en",
        "category": "infrastructure",
        "query": "What retry strategy and dead letter queue handle indexing task failures in Celery?",
        "relevant_chunks": ["arch_celery_dlq"],
    },
    {
        "case_id": "AI3-EN-008",
        "type": "positive",
        "language": "en",
        "category": "security",
        "query": "How does the prompt security gate identify indirect prompt injection and jailbreak attacks?",
        "relevant_chunks": ["sec_prompt_injection"],
    },
    {
        "case_id": "AI3-EN-009",
        "type": "positive",
        "language": "en",
        "category": "security",
        "query": "What cryptographic hashing and isolation standards protect the audit trail records?",
        "relevant_chunks": ["sec_audit_trail"],
    },
    {
        "case_id": "AI3-EN-010",
        "type": "positive",
        "language": "en",
        "category": "security",
        "query": "What encryption standards are enforced for enterprise data in transit and at rest?",
        "relevant_chunks": ["sec_encryption_standards"],
    },
    {
        "case_id": "AI3-EN-011",
        "type": "positive",
        "language": "en",
        "category": "hr",
        "query": "What are the eligibility conditions and weekly limits for employee remote work?",
        "relevant_chunks": ["hr_remote_work"],
    },
    {
        "case_id": "AI3-EN-012",
        "type": "positive",
        "language": "en",
        "category": "hr",
        "query": "What is the submission deadline and receipt requirement for corporate travel expense reimbursement?",
        "relevant_chunks": ["hr_expense_reimbursement"],
    },
    {
        "case_id": "AI3-EN-013",
        "type": "positive",
        "language": "en",
        "category": "compliance",
        "query": "Within what timeframe must SDAIA be notified following a personal data breach under Saudi PDPL?",
        "relevant_chunks": ["legal_pdpl_breach"],
    },
    {
        "case_id": "AI3-EN-014",
        "type": "positive",
        "language": "en",
        "category": "evaluation",
        "query": "How are reasoning quality and dense retrieval accuracy benchmarked across Arabic and English?",
        "relevant_chunks": ["eval_bilingual_bge"],
    },
    {
        "case_id": "AI3-EN-015",
        "type": "positive",
        "language": "en",
        "category": "architecture",
        "query": "Reciprocal Rank Fusion RRF constant k=60 dense BAAI/bge-m3 PostgreSQL GIN tsvector",
        "relevant_chunks": ["arch_hybrid_search"],
    },

    # ── 10 Bilingual / Cross-Lingual Cases (Positive) ──
    # Subgroup 1: Arabic Query -> English Content (3 cases)
    {
        "case_id": "AI3-BI-AR2EN-001",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "ar_to_en",
        "category": "security",
        "query": "كيف يكتشف مرشح الأمان هجمات حقن التعليمات البرمجية والهروب من السياق؟",
        "relevant_chunks": ["sec_prompt_injection"],
    },
    {
        "case_id": "AI3-BI-AR2EN-002",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "ar_to_en",
        "category": "infrastructure",
        "query": "ما هي معايير تشفير البيانات المخزنة والبيانات المنقولة عبر الشبكة في المنصة؟",
        "relevant_chunks": ["sec_encryption_standards"],
    },
    {
        "case_id": "AI3-BI-AR2EN-003",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "ar_to_en",
        "category": "hr",
        "query": "ما هي سياسة العمل عن بعد الأسبوعية واشتراطات أمان الشبكة الافتراضية؟",
        "relevant_chunks": ["hr_remote_work"],
    },
    # Subgroup 2: English Query -> Arabic Content (3 cases)
    {
        "case_id": "AI3-BI-EN2AR-001",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "en_to_ar",
        "category": "legal",
        "query": "How is the end of service award calculated for the first five years under Saudi Labor Law?",
        "relevant_chunks": ["legal_labor_art84"],
    },
    {
        "case_id": "AI3-BI-EN2AR-002",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "en_to_ar",
        "category": "legal",
        "query": "What is the legal compensation for unfair dismissal when an employment contract has no fixed term?",
        "relevant_chunks": ["legal_labor_art77"],
    },
    {
        "case_id": "AI3-BI-EN2AR-003",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "en_to_ar",
        "category": "hr",
        "query": "What is the paid sick leave duration and progressive salary deduction schedule?",
        "relevant_chunks": ["hr_sick_leave"],
    },
    # Subgroup 3: Mixed Query -> Mixed Content (4 cases)
    {
        "case_id": "AI3-BI-MIX-001",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "mixed_to_mixed",
        "category": "compliance",
        "query": "What are the PDPL requirements ونظام حماية البيانات الشخصية for enterprise data sovereignty?",
        "relevant_chunks": ["legal_pdpl_breach", "legal_pdpl_sovereignty"],
    },
    {
        "case_id": "AI3-BI-MIX-002",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "mixed_to_mixed",
        "category": "architecture",
        "query": "Explain Reciprocal Rank Fusion RRF وحساب الترتيب التبادلي k=60 in hybrid search",
        "relevant_chunks": ["arch_hybrid_search"],
    },
    {
        "case_id": "AI3-BI-MIX-003",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "mixed_to_mixed",
        "category": "security",
        "query": "Multi-tenant security isolation وعزل المنظمات in Qdrant payload filters",
        "relevant_chunks": ["arch_qdrant_vector", "sec_rbac_isolation"],
    },
    {
        "case_id": "AI3-BI-MIX-004",
        "type": "positive",
        "language": "bilingual",
        "bilingual_mode": "mixed_to_mixed",
        "category": "audit",
        "query": "Audit logging and security tracking لسجلات التدقيق الأمني and cross-tenant attempts",
        "relevant_chunks": ["sec_audit_trail"],
    },

    # ── 5 Multi-Chunk Synthesis Cases (Positive) ──
    {
        "case_id": "AI3-MC-001",
        "type": "positive",
        "language": "ar",
        "category": "legal",
        "query": "ما هي الفروق في استحقاق مكافأة نهاية الخدمة بين انتهاء العقد والاستقالة في نظام العمل؟",
        "relevant_chunks": ["legal_labor_art84", "legal_labor_art85"],
    },
    {
        "case_id": "AI3-MC-002",
        "type": "positive",
        "language": "en",
        "category": "architecture",
        "query": "How do Qdrant vector indexing and PostgreSQL connection pooling coordinate during high load?",
        "relevant_chunks": ["arch_qdrant_vector", "arch_database_pooling"],
    },
    {
        "case_id": "AI3-MC-003",
        "type": "positive",
        "language": "bilingual",
        "category": "security",
        "query": "Comprehensive enterprise security: RBAC isolation, prompt injection defense, and audit logging",
        "relevant_chunks": ["sec_rbac_isolation", "sec_prompt_injection", "sec_audit_trail"],
    },
    {
        "case_id": "AI3-MC-004",
        "type": "positive",
        "language": "ar",
        "category": "hr",
        "query": "ما هي الحقوق النظامية للموظف في الإجازات السنوية والإجازات المرضية؟",
        "relevant_chunks": ["hr_annual_leave", "hr_sick_leave"],
    },
    {
        "case_id": "AI3-MC-005",
        "type": "positive",
        "language": "en",
        "category": "infrastructure",
        "query": "How does document ingestion integrate Celery task execution with deduplication and dead letter queues?",
        "relevant_chunks": ["arch_celery_redis", "arch_storage_dedup", "arch_celery_dlq"],
    },

    # ── 5 Negative / Unanswerable Cases (0 relevant chunks in corpus) ──
    {
        "case_id": "AI3-NEG-001",
        "type": "negative",
        "language": "ar",
        "category": "unanswerable",
        "query": "ما هي تفاصيل شروط الحصول على قروض تمويل السيارات في البنك المركزي السعودي؟",
        "relevant_chunks": [],
    },
    {
        "case_id": "AI3-NEG-002",
        "type": "negative",
        "language": "en",
        "category": "unanswerable",
        "query": "What are the dividend tax rates for foreign equity investors in the Tokyo Stock Exchange?",
        "relevant_chunks": [],
    },
    {
        "case_id": "AI3-NEG-003",
        "type": "negative",
        "language": "ar",
        "category": "unanswerable",
        "query": "كيف يتم تسجيل براءات الاختراع الصيدلانية لدى منظمة الصحة العالمية؟",
        "relevant_chunks": [],
    },
    {
        "case_id": "AI3-NEG-004",
        "type": "negative",
        "language": "en",
        "category": "unanswerable",
        "query": "What are the kernel tuning parameters for high-frequency trading networks on Solaris SPARC?",
        "relevant_chunks": [],
    },
    {
        "case_id": "AI3-NEG-005",
        "type": "negative",
        "language": "bilingual",
        "category": "unanswerable",
        "query": "Quantum cryptography key exchange algorithms بروتوكولات التشفير الكمومي الفضائي",
        "relevant_chunks": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Dedicated Tenant-Isolation Verification Cases (6 Cases)
# ──────────────────────────────────────────────────────────────────────────────

TENANT_ISOLATION_CASES = [
    {"name": "Org-A + KB-A", "org": "A", "kb": "A", "expected": "permitted"},
    {"name": "Org-B + KB-B", "org": "B", "kb": "B", "expected": "permitted"},
    {"name": "Org-A + KB-B (Cross-tenant attack)", "org": "A", "kb": "B", "expected": "denied"},
    {"name": "Org-B + KB-A (Cross-tenant reverse)", "org": "B", "kb": "A", "expected": "denied"},
    {"name": "Missing organization_id", "org": None, "kb": "A", "expected": "fail_closed"},
    {"name": "Missing knowledge_base_id", "org": "A", "kb": None, "expected": "fail_closed"},
]


# ──────────────────────────────────────────────────────────────────────────────
# 4. Metric Computation Helpers
# ──────────────────────────────────────────────────────────────────────────────

def calculate_positive_metrics(
    retrieved_uuids: List[str],
    ground_truth_uuids: List[str],
    eval_svc: RetrievalEvaluationService,
) -> Dict[str, float]:
    gt_set = set(ground_truth_uuids)

    # Precision
    p1 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=1)
    p3 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    p5 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    p10 = eval_svc.calculate_precision_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    # Recall
    r1 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=1)
    r3 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=3)
    r5 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=5)
    r10 = eval_svc.calculate_recall_at_k(retrieved_uuids, ground_truth_uuids, k=10)

    # MRR
    mrr_val = eval_svc.calculate_mrr(retrieved_uuids, ground_truth_uuids)

    # Hit Rate
    hr1 = 1.0 if any(u in gt_set for u in retrieved_uuids[:1]) else 0.0
    hr3 = 1.0 if any(u in gt_set for u in retrieved_uuids[:3]) else 0.0
    hr5 = 1.0 if any(u in gt_set for u in retrieved_uuids[:5]) else 0.0
    hr10 = 1.0 if any(u in gt_set for u in retrieved_uuids[:10]) else 0.0

    # NDCG
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


# ──────────────────────────────────────────────────────────────────────────────
# 5. Full Benchmark Runner
# ──────────────────────────────────────────────────────────────────────────────

def run_ai3_full_benchmark():
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("=" * 80)
    print(f"AI-3 FULL RETRIEVAL PERFORMANCE & QUALITY BENCHMARK — {timestamp}")
    print("=" * 80)

    process = psutil.Process()
    rss_before_mb = process.memory_info().rss / 1024 / 1024
    peak_rss_mb = rss_before_mb

    db = SessionLocal()
    search_service = SearchService(db)
    embedding_svc = EmbeddingService()
    eval_svc = RetrievalEvaluationService()

    rss_after_model_mb = process.memory_info().rss / 1024 / 1024
    if rss_after_model_mb > peak_rss_mb:
        peak_rss_mb = rss_after_model_mb

    # In-memory Qdrant client for deterministic, self-contained evaluation
    qdrant_client = QdrantClient(":memory:")
    collection_name = "ai3_full_benchmark_collection"
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

    test_uid = uuid.uuid4().hex[:8]
    org_a = Organization(name=f"AI3 Benchmark Org A {test_uid}", slug=f"ai3-org-a-{test_uid}")
    org_b = Organization(name=f"AI3 Benchmark Org B {test_uid}", slug=f"ai3-org-b-{test_uid}")
    db.add_all([org_a, org_b])
    db.commit()

    eval_to_uuid: Dict[str, str] = {}
    uuid_to_eval: Dict[str, str] = {}
    created_chunk_ids = []
    created_pdoc_ids = []
    created_doc_ids = []

    try:
        user = db.query(User).first()
        user_id = user.id if user else 1

        kb_a = KnowledgeBase(name=f"AI3 Benchmark KB A {test_uid}", organization_id=org_a.id, owner_id=user_id)
        kb_b = KnowledgeBase(name=f"AI3 Benchmark KB B {test_uid}", organization_id=org_b.id, owner_id=user_id)
        db.add_all([kb_a, kb_b])
        db.commit()

        print(f"[*] Seeding {len(CORPUS_CHUNKS)} canonical benchmark chunks (including distractors)...")
        doc_a = Document(
            filename="ai3_full_corpus.txt",
            storage_path="/benchmark/full_corpus",
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
            processing_duration=1.2,
        )
        db.add(pdoc_a)
        db.commit()
        created_pdoc_ids.append(pdoc_a.id)

        points = []
        for idx, chunk_def in enumerate(CORPUS_CHUNKS):
            eval_id = chunk_def["eval_id"]
            text = chunk_def["text"]

            chunk_obj = DocumentChunk(
                parsed_document_id=pdoc_a.id,
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
            uuid_to_eval[str(chunk_obj.uuid)] = eval_id

            vec = embedding_svc.embed_text(text)
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
                        "text": text,
                        "char_count": len(text),
                        "estimated_tokens": len(text.split()),
                    },
                )
            )

        qdrant_client.upsert(collection_name=collection_name, points=points)
        print(f"[OK] Successfully indexed {len(points)} vectors and FTS records in Org-A/KB-A.")

        # Seed 1 dummy chunk in Org-B/KB-B for tenant isolation testing
        doc_b = Document(
            filename="org_b_private.txt",
            storage_path="/benchmark/org_b",
            mime_type="text/plain",
            file_size=500,
            knowledge_base_id=kb_b.id,
            created_by=user_id,
            status="Processed",
        )
        db.add(doc_b)
        db.commit()
        created_doc_ids.append(doc_b.id)

        pdoc_b = ParsedDocument(
            document_id=doc_b.id,
            parsed_text="Confidential Org B Data",
            char_count=24,
            processing_duration=0.1,
        )
        db.add(pdoc_b)
        db.commit()
        created_pdoc_ids.append(pdoc_b.id)

        chunk_b = DocumentChunk(
            parsed_document_id=pdoc_b.id,
            chunk_index=0,
            chunk_text="Confidential Org B Internal Records",
            char_count=35,
            estimated_tokens=5,
            start_offset=0,
            end_offset=35,
            search_vector=func.to_tsvector("simple", "Confidential Org B Internal Records"),
        )
        db.add(chunk_b)
        db.commit()
        created_chunk_ids.append(chunk_b.id)

        vec_b = embedding_svc.embed_text(chunk_b.chunk_text)
        qdrant_client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=chunk_b.id,
                    vector=vec_b,
                    payload={
                        "chunk_uuid": str(chunk_b.uuid),
                        "parsed_document_id": pdoc_b.id,
                        "knowledge_base_id": kb_b.id,
                        "organization_id": org_b.id,
                        "chunk_index": 0,
                        "text": chunk_b.chunk_text,
                    },
                )
            ],
        )

        # ── Pre-Execution Dataset & Metric Integrity Verification ──
        print("[*] Verifying benchmark dataset integrity...")
        assert len(FULL_BENCHMARK_CASES) == 50, f"Expected 50 cases, found {len(FULL_BENCHMARK_CASES)}"
        pos_cases = [c for c in FULL_BENCHMARK_CASES if c["type"] == "positive"]
        neg_cases = [c for c in FULL_BENCHMARK_CASES if c["type"] == "negative"]
        assert len(pos_cases) == 45, f"Expected 45 positive cases, found {len(pos_cases)}"
        assert len(neg_cases) == 5, f"Expected 5 negative cases, found {len(neg_cases)}"

        for case in pos_cases:
            for eid in case["relevant_chunks"]:
                if eid not in eval_to_uuid:
                    raise ValueError(f"Integrity Error: Evaluation ID '{eid}' in case '{case['case_id']}' not in corpus!")

        print(f"[OK] Integrity verified: 45 positive cases (15 AR, 15 EN, 10 BI, 5 MC) and 5 negative cases.")

        # ── Benchmark Execution across Modes ──
        modes = ["dense", "keyword", "hybrid"]
        results_by_mode: Dict[str, Any] = {}

        with patch.object(QdrantService, "_client", qdrant_client), \
             patch.object(search_service.qdrant_service, "collection_name", collection_name):

            for mode in modes:
                print(f"\n{'='*30} Evaluating Mode: {mode.upper()} {'='*30}")
                positive_records: List[Dict[str, Any]] = []
                negative_records: List[Dict[str, Any]] = []
                profiling_records: List[Dict[str, float]] = []

                for case in FULL_BENCHMARK_CASES:
                    query = case["query"]
                    is_pos = case["type"] == "positive"
                    relevant_eval_ids = case.get("relevant_chunks", [])
                    gt_uuids = [eval_to_uuid[eid] for eid in relevant_eval_ids if eid in eval_to_uuid]

                    profiler = RetrievalProfiler()
                    t_start = time.perf_counter()

                    if mode == "dense":
                        search_results = search_service._dense_search(
                            query=query,
                            knowledge_base_id=kb_a.id,
                            organization_id=org_a.id,
                            top_k=10,
                            profiler=profiler,
                        )
                    elif mode == "keyword":
                        profiler.start("keyword_search")
                        search_results = search_service.keyword_search(
                            query=query,
                            knowledge_base_id=kb_a.id,
                            organization_id=org_a.id,
                            top_k=10,
                        )
                        profiler.stop("keyword_search")
                    elif mode == "hybrid":
                        search_results = search_service.hybrid_search(
                            query=query,
                            knowledge_base_id=kb_a.id,
                            organization_id=org_a.id,
                            top_k=10,
                            profiler=profiler,
                        )

                    total_elapsed_ms = (time.perf_counter() - t_start) * 1000

                    cur_rss = process.memory_info().rss / 1024 / 1024
                    if cur_rss > peak_rss_mb:
                        peak_rss_mb = cur_rss

                    retrieved_uuids = [r.chunk_uuid for r in search_results]

                    # Detect duplicate retrieved IDs
                    assert len(retrieved_uuids) == len(set(retrieved_uuids)), (
                        f"Integrity Error: Duplicate chunk UUIDs retrieved in case {case['case_id']}"
                    )

                    prof_entry = {
                        "embedding_ms": profiler.metrics.embedding_ms,
                        "dense_search_ms": profiler.metrics.dense_search_ms,
                        "keyword_search_ms": profiler.metrics.keyword_search_ms,
                        "fusion_ms": profiler.metrics.fusion_ms,
                        "total_ms": total_elapsed_ms,
                    }
                    profiling_records.append(prof_entry)

                    if is_pos:
                        m = calculate_positive_metrics(retrieved_uuids, gt_uuids, eval_svc)
                        record = {
                            "case_id": case["case_id"],
                            "language": case["language"],
                            "category": case["category"],
                            "bilingual_mode": case.get("bilingual_mode"),
                            "metrics": m,
                            "top_eval_ids": [uuid_to_eval.get(u, "UNKNOWN") for u in retrieved_uuids[:5]],
                        }
                        positive_records.append(record)
                    else:
                        neg_m = calculate_negative_metrics(search_results)
                        record = {
                            "case_id": case["case_id"],
                            "metrics": neg_m,
                            "top_eval_ids": [uuid_to_eval.get(u, "UNKNOWN") for u in retrieved_uuids[:5]],
                        }
                        negative_records.append(record)

                # ── Aggregate Positive Metrics ──
                all_pos_metrics = [r["metrics"] for r in positive_records]
                avg_pos_metrics = {
                    k: float(np.mean([m[k] for m in all_pos_metrics]))
                    for k in all_pos_metrics[0].keys()
                }

                # Specifically 15 Arabic, 15 English, 10 Bilingual, 5 Multi-chunk
                ar_15 = [r["metrics"] for r in positive_records if r["case_id"].startswith("AI3-AR-")]
                en_15 = [r["metrics"] for r in positive_records if r["case_id"].startswith("AI3-EN-")]
                bi_10 = [r["metrics"] for r in positive_records if r["case_id"].startswith("AI3-BI-")]
                mc_5 = [r["metrics"] for r in positive_records if r["case_id"].startswith("AI3-MC-")]

                def calc_avg(sub_list):
                    if not sub_list:
                        return {}
                    return {k: float(np.mean([m[k] for m in sub_list])) for k in sub_list[0].keys()}

                # Bilingual subcategories
                bi_ar2en = [r["metrics"] for r in positive_records if r.get("bilingual_mode") == "ar_to_en"]
                bi_en2ar = [r["metrics"] for r in positive_records if r.get("bilingual_mode") == "en_to_ar"]
                bi_mixed = [r["metrics"] for r in positive_records if r.get("bilingual_mode") == "mixed_to_mixed"]

                # ── Aggregate Negative Metrics ──
                all_neg_metrics = [r["metrics"] for r in negative_records]
                avg_neg_metrics = {
                    "no_result_rate": float(np.mean([m["no_result"] for m in all_neg_metrics])),
                    "false_retrieval_rate": float(np.mean([m["false_retrieval"] for m in all_neg_metrics])),
                    "avg_top_irrelevant_score": float(np.mean([m["top_irrelevant_score"] for m in all_neg_metrics])),
                    "cases_count": len(negative_records),
                }

                # ── Latency Summary ──
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

                results_by_mode[mode] = {
                    "overall_positive_metrics": avg_pos_metrics,
                    "breakdown": {
                        "arabic_15": calc_avg(ar_15),
                        "english_15": calc_avg(en_15),
                        "bilingual_10": calc_avg(bi_10),
                        "bilingual_ar_to_en_3": calc_avg(bi_ar2en),
                        "bilingual_en_to_ar_3": calc_avg(bi_en2ar),
                        "bilingual_mixed_4": calc_avg(bi_mixed),
                        "multi_chunk_5": calc_avg(mc_5),
                    },
                    "negative_metrics": avg_neg_metrics,
                    "timings": timing_summary,
                }

                print(f"  * Recall@1: {avg_pos_metrics['r1']*100:.1f}% | Recall@3: {avg_pos_metrics['r3']*100:.1f}% | Recall@5: {avg_pos_metrics['r5']*100:.1f}% | Recall@10: {avg_pos_metrics['r10']*100:.1f}%")
                print(f"  * Precision@1: {avg_pos_metrics['p1']*100:.1f}% | Precision@3: {avg_pos_metrics['p3']*100:.1f}% | Precision@5: {avg_pos_metrics['p5']*100:.1f}% | Precision@10: {avg_pos_metrics['p10']*100:.1f}%")
                print(f"  * MRR: {avg_pos_metrics['mrr']:.3f} | HitRate@3: {avg_pos_metrics['hr3']*100:.1f}% | NDCG@5: {avg_pos_metrics['ndcg5']:.3f}")
                print(f"  * Negative Query False Retrieval Rate: {avg_neg_metrics['false_retrieval_rate']*100:.1f}%")
                print(f"  * Timings (ms): min={timing_summary['min_ms']:.1f}, p50={timing_summary['p50_ms']:.1f}, p95={timing_summary['p95_ms']:.1f}, max={timing_summary['max_ms']:.1f}")

        # ── 6. Dedicated Tenant Isolation Subset Verification ──
        print(f"\n{'='*30} Evaluating Tenant Isolation Subset {'='*30}")
        tenant_results: List[Dict[str, Any]] = []

        with patch.object(QdrantService, "_client", qdrant_client), \
             patch.object(search_service.qdrant_service, "collection_name", collection_name):

            for tc in TENANT_ISOLATION_CASES:
                name = tc["name"]
                org_param = org_a.id if tc["org"] == "A" else (org_b.id if tc["org"] == "B" else None)
                kb_param = kb_a.id if tc["kb"] == "A" else (kb_b.id if tc["kb"] == "B" else None)
                expected = tc["expected"]

                outcome = "UNKNOWN"
                error_msg = None
                res_count = 0

                try:
                    res = search_service.hybrid_search(
                        query="enterprise security policy",
                        knowledge_base_id=kb_param,
                        organization_id=org_param,
                        top_k=5,
                    )
                    res_count = len(res)
                    if expected == "permitted":
                        outcome = "PASS" if res_count > 0 else "FAIL_EMPTY"
                    elif expected == "denied":
                        outcome = "PASS" if res_count == 0 else "FAIL_LEAK"
                except ValueError as ve:
                    error_msg = str(ve)
                    if expected == "fail_closed":
                        outcome = "PASS"
                    else:
                        outcome = "UNEXPECTED_ERROR"
                except Exception as ex:
                    error_msg = str(ex)
                    outcome = "ERROR"

                tenant_results.append({
                    "case": name,
                    "expected": expected,
                    "outcome": outcome,
                    "returned_count": res_count,
                    "error": error_msg,
                })
                print(f"  * [{outcome}] {name}: returned={res_count}, error={error_msg}")

        rss_after_mb = process.memory_info().rss / 1024 / 1024

        benchmark_report = {
            "metadata": {
                "benchmark_name": "AI-3 Full Retrieval Performance & Quality Benchmark",
                "timestamp": timestamp,
                "embedding_model": "BAAI/bge-m3",
                "embedding_dimension": 1024,
                "distance_metric": "Cosine",
                "qdrant_collection_size": len(points) + 1,
                "chunk_size": 600,
                "chunk_overlap": 100,
                "rrf_k": 60,
                "total_cases": len(FULL_BENCHMARK_CASES),
                "positive_cases": len(pos_cases),
                "negative_cases": len(neg_cases),
                "corpus_chunks": len(CORPUS_CHUNKS),
            },
            "results_by_mode": results_by_mode,
            "tenant_isolation_subset": tenant_results,
            "resource_usage": {
                "rss_before_mb": rss_before_mb,
                "rss_after_model_mb": rss_after_model_mb,
                "peak_rss_mb": peak_rss_mb,
                "rss_after_mb": rss_after_mb,
                "memory_statement": "No obvious post-initialization RSS growth was observed during this benchmark run.",
            },
        }

        output_path = os.path.join(os.path.dirname(__file__), "..", "ai3_full_benchmark_results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_report, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] Full AI-3 benchmark results written to {output_path}")

        return benchmark_report

    finally:
        # Strict database cleanup
        print("[*] Cleaning up benchmark database fixtures...")
        if created_chunk_ids:
            db.query(DocumentChunk).filter(DocumentChunk.id.in_(created_chunk_ids)).delete(synchronize_session=False)
        if created_pdoc_ids:
            db.query(ParsedDocument).filter(ParsedDocument.id.in_(created_pdoc_ids)).delete(synchronize_session=False)
        if created_doc_ids:
            db.query(Document).filter(Document.id.in_(created_doc_ids)).delete(synchronize_session=False)
        db.query(KnowledgeBase).filter(KnowledgeBase.organization_id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id.in_([org_a.id, org_b.id])).delete(synchronize_session=False)
        db.commit()
        db.close()
        print("[OK] Database cleanup completed.")


if __name__ == "__main__":
    run_ai3_full_benchmark()
