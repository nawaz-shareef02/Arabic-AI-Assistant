import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
from sqlalchemy import text
from app.database.session import SessionLocal
from app.models.parsed_document import ParsedDocument
from app.models.document import Document
from app.services.qdrant_service import QdrantService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repair_qdrant")

def repair_qdrant_payloads():
    logger.info("Starting Qdrant Payload Repair Audit...")
    db = SessionLocal()
    qdrant = QdrantService()
    
    try:
        # Scroll through all points in Qdrant collection
        offset = None
        total_scanned = 0
        repaired_count = 0
        
        while True:
            scroll_result, next_offset = qdrant.client.scroll(
                collection_name=qdrant.collection_name,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            
            if not scroll_result:
                break
                
            total_scanned += len(scroll_result)
            
            for point in scroll_result:
                payload = point.payload or {}
                kb_id = payload.get("knowledge_base_id")
                parsed_doc_id = payload.get("parsed_document_id")
                
                if kb_id is None:
                    if parsed_doc_id is not None:
                        # Find knowledge_base_id from DB
                        parsed_doc = db.query(ParsedDocument).filter(ParsedDocument.id == parsed_doc_id).first()
                        if parsed_doc and parsed_doc.document:
                            actual_kb_id = parsed_doc.document.knowledge_base_id
                            # Update point payload in Qdrant
                            qdrant.client.set_payload(
                                collection_name=qdrant.collection_name,
                                payload={"knowledge_base_id": int(actual_kb_id)},
                                points=[point.id]
                            )
                            repaired_count += 1
                            logger.info(f"Repaired Point {point.id}: set knowledge_base_id = {actual_kb_id}")
                        else:
                            logger.warning(f"Could not find ParsedDocument/Document in DB for parsed_document_id {parsed_doc_id}")
                    else:
                        logger.warning(f"Point {point.id} has no parsed_document_id in payload")
            
            if not next_offset:
                break
            offset = next_offset
            
        logger.info(f"Audit complete. Total vectors scanned: {total_scanned}, Repaired: {repaired_count}")
        
    except Exception as e:
        logger.exception(f"Payload repair failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    repair_qdrant_payloads()
