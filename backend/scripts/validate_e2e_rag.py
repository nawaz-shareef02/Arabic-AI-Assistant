import sys
import os
import time
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
from fastapi.testclient import TestClient
from app.main import app
from app.database.session import SessionLocal
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.services.qdrant_service import QdrantService
from app.services.search_service import SearchService
from app.services.rag_service import RAGService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("e2e_validation")

def run_validation():
    logger.info("==================================================")
    logger.info("STARTING END-TO-END PRODUCTION VALIDATION")
    logger.info("==================================================")
    
    client = TestClient(app)
    db = SessionLocal()
    
    try:
        # 1. Test Swagger OAuth Token Endpoint (/api/v1/auth/token)
        logger.info("--- Step 1: Testing Swagger OAuth2 Endpoint (/api/v1/auth/token) ---")
        token_res = client.post(
            "/api/v1/auth/token",
            data={"username": "admin@arabiq.ai", "password": "Password123!"}
        )
        if token_res.status_code == 400 or token_res.status_code == 401:
            # Register user first if not present
            logger.info("Registering test user...")
            reg_res = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "admin@arabiq.ai",
                    "password": "Password123!",
                    "full_name": "Admin User",
                    "organization": "ArabIQ",
                    "preferred_language": "ar"
                }
            )
            assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
            token_res = client.post(
                "/api/v1/auth/token",
                data={"username": "admin@arabiq.ai", "password": "Password123!"}
            )
            
        assert token_res.status_code == 200, f"Swagger OAuth failed: {token_res.text}"
        access_token = token_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        logger.info("✓ Swagger OAuth (/api/v1/auth/token) PASSED")

        # 2. Test Frontend JSON Login (/api/v1/auth/login)
        logger.info("--- Step 2: Testing Frontend Login Endpoint (/api/v1/auth/login) ---")
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@arabiq.ai", "password": "Password123!"}
        )
        assert login_res.status_code == 200, f"Frontend login failed: {login_res.text}"
        logger.info("✓ Frontend JSON Login (/api/v1/auth/login) PASSED")

        # 3. Create Knowledge Base
        logger.info("--- Step 3: Creating Test Knowledge Base ---")
        kb_res = client.post(
            "/api/v1/knowledge-bases",
            json={"name": "Production Validation KB", "description": "KB for E2E validation"},
            headers=headers
        )
        assert kb_res.status_code == 201, f"KB creation failed: {kb_res.text}"
        kb_data = kb_res.json()
        kb_id = kb_data["id"]
        kb_uuid = kb_data["uuid"]
        logger.info(f"✓ KB Created: ID={kb_id}, UUID={kb_uuid}")

        # 4. Upload Document
        logger.info("--- Step 4: Uploading Document ---")
        doc_content = (
            "ArabIQ is an Enterprise Arabic-English AI Knowledge Platform built with FastAPI, PostgreSQL, and Qdrant. "
            "It supports high-precision Retrieval-Augmented Generation (RAG) for Arabic and English documents. "
            "Semantic search uses BAAI/bge-m3 embeddings to retrieve relevant document chunks."
        ).encode("utf-8")
        
        files = {"file": ("test_arabiq_doc.txt", io.BytesIO(doc_content), "text/plain")}
        data = {"knowledge_base_uuid": kb_uuid}
        
        upload_res = client.post(
            "/api/v1/documents/upload",
            files=files,
            data=data,
            headers=headers
        )
        assert upload_res.status_code == 201, f"Upload failed: {upload_res.text}"
        doc_uuid = upload_res.json()["uuid"]
        logger.info(f"✓ Document Uploaded: UUID={doc_uuid}")

        # 5. Process Document (Parsing, Chunking, Embedding, Indexing)
        logger.info("--- Step 5: Processing Document ---")
        from app.services.document_service import DocumentService
        user = db.query(User).filter(User.email == "admin@arabiq.ai").first()
        doc_service = DocumentService(db)
        doc_service.process_document(doc_uuid, user.id)
        logger.info("✓ Document Processing completed")

        # 6. Verify Qdrant Payload & Indexing
        logger.info("--- Step 6: Verifying Qdrant Vector Payload ---")
        qdrant_service = QdrantService()
        points = qdrant_service.search(query="ArabIQ Platform", knowledge_base_id=kb_id, limit=5)
        logger.info(f"Returned points count for KB {kb_id}: {len(points)}")
        assert len(points) > 0, "No vectors returned from Qdrant search!"
        
        for point in points:
            payload_kb_id = point.payload.get("knowledge_base_id")
            logger.info(f"Point ID: {point.id}, Payload KB ID: {payload_kb_id}, Score: {point.score:.4f}")
            assert payload_kb_id == kb_id, f"Payload KB ID mismatch! Expected {kb_id}, got {payload_kb_id}"
            assert point.payload.get("text"), "Point text missing!"
        logger.info("✓ Qdrant payload verification PASSED")

        # 7. Test SearchService
        logger.info("--- Step 7: Testing SearchService ---")
        search_service = SearchService(db)
        search_results = search_service.semantic_search(
            query="What is ArabIQ built with?",
            knowledge_base_id=kb_id,
            top_k=5
        )
        logger.info(f"SearchService returned {len(search_results)} results")
        assert len(search_results) > 0, "SearchService returned 0 results!"
        logger.info("✓ SearchService PASSED")

        # 8. Test RAGService.ask
        logger.info("--- Step 8: Testing RAGService.ask ---")
        rag_service = RAGService(db)
        rag_response = rag_service.ask(
            question="What framework and vector database does ArabIQ use?",
            knowledge_base_id=kb_id
        )
        logger.info(f"RAG Answer: {rag_response.get('answer')}")
        logger.info(f"RAG Sources: {rag_response.get('sources')}")
        assert "FastAPI" in rag_response["answer"] or "Qdrant" in rag_response["answer"] or len(rag_response["sources"]) > 0
        assert rag_response["answer"] != "I couldn't find enough information in the uploaded documents."
        logger.info("✓ RAGService.ask PASSED")

        # 9. Test RAGService.stream_ask
        logger.info("--- Step 9: Testing RAGService.stream_ask ---")
        stream_chunks = list(rag_service.stream_ask(
            question="Summarize ArabIQ capabilities.",
            knowledge_base_id=kb_id
        ))
        streamed_text = "".join(stream_chunks)
        logger.info(f"Streamed Text: {streamed_text}")
        assert len(streamed_text) > 0
        assert streamed_text != "I couldn't find enough information in the uploaded documents."
        logger.info("✓ RAGService.stream_ask PASSED")

        logger.info("==================================================")
        logger.info("ALL END-TO-END VALIDATION TESTS PASSED SUCCESSFULLY! 🚀")
        logger.info("==================================================")

    except Exception as e:
        logger.exception(f"Validation failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_validation()
