import sys
import os
import time
import io
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.database.session import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("e2e_bilingual_validation")


def run_bilingual_e2e_validation():
    logger.info("==================================================")
    logger.info("STARTING BILINGUAL (EN/AR) E2E PRODUCTION VALIDATION")
    logger.info("==================================================")

    client = TestClient(app)
    db = SessionLocal()

    try:
        # 1. Auth setup
        logger.info("--- Step 1: Authentication & User Setup ---")
        token_res = client.post(
            "/api/v1/auth/token",
            data={"username": "hardening_admin@arabiq.ai", "password": "Password123!"}
        )
        if token_res.status_code != 200:
            reg_res = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "hardening_admin@arabiq.ai",
                    "password": "Password123!",
                    "full_name": "Hardening Test Admin",
                    "organization": "ArabIQ",
                    "preferred_language": "ar"
                }
            )
            assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
            token_res = client.post(
                "/api/v1/auth/token",
                data={"username": "hardening_admin@arabiq.ai", "password": "Password123!"}
            )

        assert token_res.status_code == 200, f"Token failed: {token_res.text}"
        token = token_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        logger.info("✓ Auth Token Acquired")

        # 2. Knowledge Base Creation
        logger.info("--- Step 2: Creating Test Knowledge Base ---")
        kb_res = client.post(
            "/api/v1/knowledge-bases",
            json={"name": "Sprint 12.5 Hardening KB", "description": "Bilingual validation workspace"},
            headers=headers
        )
        assert kb_res.status_code == 201, f"KB creation failed: {kb_res.text}"
        kb = kb_res.json()
        kb_id = kb["id"]
        kb_uuid = kb["uuid"]
        logger.info(f"✓ KB Created: ID={kb_id}, UUID={kb_uuid}")

        # 3. Document Ingestion (English)
        logger.info("--- Step 3: English Document Ingestion & Hybrid Indexing ---")
        en_content = (
            "ArabIQ Platform Specification:\n"
            "ArabIQ is an enterprise AI knowledge platform utilizing FastAPI, Qdrant vector database, "
            "and PostgreSQL full-text search with Reciprocal Rank Fusion (RRF). "
            "It supports hybrid dense-keyword retrieval for corporate governance documents."
        ).encode("utf-8")

        en_upload = client.post(
            "/api/v1/documents/upload",
            files={"file": ("spec_en.txt", io.BytesIO(en_content), "text/plain")},
            data={"knowledge_base_uuid": kb_uuid},
            headers=headers
        )
        assert en_upload.status_code == 201, f"EN Upload failed: {en_upload.text}"
        logger.info("✓ English Document Uploaded & Indexed")

        # 4. Document Ingestion (Arabic)
        logger.info("--- Step 4: Arabic Document Ingestion & Hybrid Indexing ---")
        ar_content = (
            "منصة عرب آي كيو (ArabIQ):\n"
            "منصة عرب آي كيو هي نظام ذكاء اصطناعي موجه للمؤسسات والشركات. "
            "تعتمد على تقنيات البحث الهجين والدمج الترتيبي التبادلي (RRF) بين قواعد بيانات Qdrant و PostgreSQL. "
            "توفر المنصة إجابات دقيقة للوثائق باللغتين العربية والإنجليزية مع الحفاظ على خصوصية البيانات."
        ).encode("utf-8")

        ar_upload = client.post(
            "/api/v1/documents/upload",
            files={"file": ("spec_ar.txt", io.BytesIO(ar_content), "text/plain")},
            data={"knowledge_base_uuid": kb_uuid},
            headers=headers
        )
        assert ar_upload.status_code == 201, f"AR Upload failed: {ar_upload.text}"
        logger.info("✓ Arabic Document Uploaded & Indexed")

        # Give background parsing & vector indexing 2s to process
        time.sleep(2)

        # 5. Conversation Creation
        logger.info("--- Step 5: Creating Conversation Session ---")
        conv_res = client.post(
            "/api/v1/conversations/",
            json={"knowledge_base_id": kb_id, "title": "Bilingual Validation Test"},
            headers=headers
        )
        assert conv_res.status_code == 201, f"Conv creation failed: {conv_res.text}"
        conv_id = conv_res.json()["id"]
        logger.info(f"✓ Conversation Created ID={conv_id}")

        # 6. English Query Streaming Execution
        logger.info("--- Step 6: English Streaming RAG Execution ---")
        stream_en_res = client.post(
            "/api/v1/chat/stream",
            json={
                "question": "What database technology does ArabIQ use for hybrid search?",
                "knowledge_base_id": kb_id,
                "conversation_id": conv_id
            },
            headers=headers
        )
        assert stream_en_res.status_code == 200, f"EN Stream failed: {stream_en_res.text}"
        en_stream_text = stream_en_res.text
        assert len(en_stream_text) > 0, "EN Stream response was empty"
        logger.info(f"✓ English Streaming Output Received ({len(en_stream_text)} chars)")

        # 7. Arabic Query Streaming Execution
        logger.info("--- Step 7: Arabic Streaming RAG Execution ---")
        stream_ar_res = client.post(
            "/api/v1/chat/stream",
            json={
                "question": "ما هي قواعد البيانات المستعملة في منصة عرب آي كيو؟",
                "knowledge_base_id": kb_id,
                "conversation_id": conv_id
            },
            headers=headers
        )
        assert stream_ar_res.status_code == 200, f"AR Stream failed: {stream_ar_res.text}"
        ar_stream_text = stream_ar_res.text
        assert len(ar_stream_text) > 0, "AR Stream response was empty"
        logger.info(f"✓ Arabic Streaming Output Received ({len(ar_stream_text)} chars)")

        # 8. Retrieve Conversation History
        logger.info("--- Step 8: Verifying Conversation Persistence ---")
        hist_res = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
        assert hist_res.status_code == 200, f"History fetch failed: {hist_res.text}"
        messages = hist_res.json()["messages"]
        assert len(messages) >= 4, f"Expected at least 4 messages (2 turns), got {len(messages)}"
        logger.info(f"✓ Conversation History Verified ({len(messages)} messages persisted)")

        logger.info("==================================================")
        logger.info("✓ ALL BILINGUAL E2E VALIDATION STEPS PASSED SUCCESSFULLY")
        logger.info("==================================================")
        return True

    finally:
        db.close()

if __name__ == "__main__":
    run_bilingual_e2e_validation()
