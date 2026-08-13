import sys
import os
import time
import io
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.database.session import SessionLocal
from app.services.classification_service import ClassificationService
from app.services.entity_extraction_service import EntityExtractionService
from app.services.metadata_enrichment_service import MetadataEnrichmentService
from app.services.document_relationship_service import DocumentRelationshipService
from app.services.knowledge_health_service import KnowledgeHealthService
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.analytics_service import AnalyticsService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("s13_validation")


def run_s13_validation():
    logger.info("==================================================")
    logger.info("STARTING SPRINT 13 KNOWLEDGE INTELLIGENCE VALIDATION")
    logger.info("==================================================")

    db = SessionLocal()
    client = TestClient(app)

    try:
        # 1. Classification Strategy Test
        logger.info("--- Step 1: Testing ClassificationService Strategy ---")
        classifier = ClassificationService()
        cat_hr = classifier.classify_document("Employee vacation and payroll policy", "hr_policy.pdf")
        assert cat_hr in ["HR", "Policies"], f"Unexpected category: {cat_hr}"
        cat_legal = classifier.classify_document("Terms of agreement contract for vendor", "contract.pdf")
        assert cat_legal in ["Contracts", "Legal"], f"Unexpected category: {cat_legal}"
        logger.info(f"✓ Classification Strategy PASSED (HR: {cat_hr}, Legal: {cat_legal})")

        # 2. Entity Extraction Test
        logger.info("--- Step 2: Testing Modular EntityExtractionService ---")
        extractor = EntityExtractionService()
        sample_text = (
            "ArabIQ AI Platform created by FastAPI and PostgreSQL. Contact admin@arabiq.ai or +1-800-555-0199. "
            "شركة عرب آي كيو في مدينة الرياض بالمملكة العربية السعودية."
        )
        entities = extractor.extract_entities(sample_text)
        assert len(entities) > 0, "No entities extracted"
        types = set(e["type"] for e in entities)
        logger.info(f"✓ Entity Extraction PASSED ({len(entities)} entities extracted, types: {types})")

        # 3. Auth & Knowledge Base Setup
        logger.info("--- Step 3: Auth & KB Setup for Live Ingestion Test ---")
        token_res = client.post(
            "/api/v1/auth/token",
            data={"username": "s13_admin@arabiq.ai", "password": "Password123!"}
        )
        if token_res.status_code != 200:
            client.post(
                "/api/v1/auth/register",
                json={
                    "email": "s13_admin@arabiq.ai",
                    "password": "Password123!",
                    "full_name": "Sprint 13 Admin",
                    "organization": "ArabIQ",
                    "preferred_language": "ar"
                }
            )
            token_res = client.post(
                "/api/v1/auth/token",
                data={"username": "s13_admin@arabiq.ai", "password": "Password123!"}
            )
        token = token_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        kb_res = client.post(
            "/api/v1/knowledge-bases",
            json={"name": "Sprint 13 Intelligence KB", "description": "KB for S13 enrichment testing"},
            headers=headers
        )
        kb_id = kb_res.json()["id"]
        kb_uuid = kb_res.json()["uuid"]

        # 4. Upload & Process Document
        logger.info("--- Step 4: Uploading Document for Ingestion & Async Intelligence ---")
        doc1_content = (
            "ArabIQ Corporate Governance and Security Policy:\n"
            "This document establishes the official security governance policies for ArabIQ AI platform. "
            "All software developers using Python and FastAPI must follow ISO-27001 guidelines. "
            "Contact security@arabiq.ai for inquiries in Riyadh, Saudi Arabia."
        ).encode("utf-8")

        upload1 = client.post(
            "/api/v1/documents/upload",
            files={"file": ("governance_policy.txt", io.BytesIO(doc1_content), "text/plain")},
            data={"knowledge_base_uuid": kb_uuid},
            headers=headers
        )
        assert upload1.status_code == 201, f"Upload failed: {upload1.text}"
        doc1_uuid = upload1.json()["uuid"]
        doc1_id = upload1.json()["id"]

        # Wait 2 seconds for processing & async intelligence thread
        time.sleep(2.5)

        # Explicitly invoke metadata enrichment & relationship detection to guarantee state
        enrichment_svc = MetadataEnrichmentService(db)
        meta1 = enrichment_svc.enrich_document(doc1_id)
        assert meta1.classification is not None, "Classification is None"
        logger.info(f"✓ Metadata Enrichment PASSED (Category: {meta1.classification}, Summary: '{meta1.summary[:50]}...')")

        # Upload a second similar document to trigger relationship detection
        doc2_content = (
            "ArabIQ Revised Corporate Governance and Security Policy:\n"
            "Updated version of the official security governance policies for ArabIQ AI platform. "
            "All software developers using Python, FastAPI, and PostgreSQL must adhere to compliance rules. "
            "Contact security@arabiq.ai in Riyadh."
        ).encode("utf-8")

        upload2 = client.post(
            "/api/v1/documents/upload",
            files={"file": ("governance_policy_v2.txt", io.BytesIO(doc2_content), "text/plain")},
            data={"knowledge_base_uuid": kb_uuid},
            headers=headers
        )
        doc2_id = upload2.json()["id"]
        doc2_uuid = upload2.json()["uuid"]
        time.sleep(2)
        enrichment_svc.enrich_document(doc2_id)

        rel_svc = DocumentRelationshipService(db)
        rels = rel_svc.detect_relationships(doc2_id)
        logger.info(f"✓ Document Relationship Detection PASSED ({len(rels)} relationships detected)")

        # 5. Knowledge Graph Service Test
        logger.info("--- Step 5: Testing KnowledgeGraphService Traversal ---")
        kg_svc = KnowledgeGraphService(db)
        subgraph = kg_svc.get_document_subgraph(doc2_id)
        assert "nodes" in subgraph and "edges" in subgraph, "Invalid subgraph"
        logger.info(f"✓ Knowledge Graph Subgraph PASSED ({len(subgraph['nodes'])} nodes, {len(subgraph['edges'])} edges)")

        # 6. Knowledge Health Service Test
        logger.info("--- Step 6: Testing KnowledgeHealthService ---")
        health_svc = KnowledgeHealthService(db)
        health_report = health_svc.calculate_health(kb_id)
        assert "score" in health_report and "dimensions" in health_report, "Invalid health report"
        logger.info(f"✓ Knowledge Health PASSED (Score: {health_report['score']}/100, Status: {health_report['status']})")

        # 7. Analytics Service Test
        logger.info("--- Step 7: Testing AnalyticsService Facade ---")
        analytics_svc = AnalyticsService(db)
        analytics_summary = analytics_svc.get_full_analytics()
        assert "total_documents" in analytics_summary, "Missing total_documents in analytics"
        logger.info(f"✓ Analytics Facade PASSED (Total Docs: {analytics_summary['total_documents']})")

        # 8. API Endpoint Verification
        logger.info("--- Step 8: Testing REST API Endpoints ---")
        res_summary = client.get("/api/v1/analytics/summary", headers=headers)
        assert res_summary.status_code == 200, "Analytics endpoint failed"

        res_health = client.get("/api/v1/analytics/health", headers=headers)
        assert res_health.status_code == 200, "Health endpoint failed"

        res_insights = client.get(f"/api/v1/documents/{doc2_uuid}/insights", headers=headers)
        assert res_insights.status_code == 200, "Insights endpoint failed"
        logger.info("✓ REST API Endpoints PASSED")

        logger.info("==================================================")
        logger.info("✓ ALL SPRINT 13 VALIDATION TESTS PASSED SUCCESSFULLY")
        logger.info("==================================================")
        return True

    finally:
        db.close()


if __name__ == "__main__":
    run_s13_validation()
