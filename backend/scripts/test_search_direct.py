import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.session import SessionLocal
from app.models.parsed_document import ParsedDocument
from app.models.document import Document
from app.models.chunk import DocumentChunk
from app.services.indexing_service import IndexingService
from app.services.qdrant_service import QdrantService
from app.services.search_service import SearchService

def run_qdrant_search_directly():
    db = SessionLocal()
    try:
        # Find first existing parsed_document in DB
        parsed_doc = db.query(ParsedDocument).first()
        if not parsed_doc:
            print("No parsed document found in DB.")
            return

        doc = db.query(Document).filter(Document.id == parsed_doc.document_id).first()
        kb_id = doc.knowledge_base_id
        print(f"Indexing ParsedDocument ID: {parsed_doc.id}, Doc UUID: {doc.uuid}, KB ID: {kb_id}")

        indexer = IndexingService(db)
        indexed_count = indexer.index_document(parsed_doc, knowledge_base_id=kb_id)
        print(f"Successfully indexed {indexed_count} chunks into Qdrant.")

        # Perform Search
        search_service = SearchService(db)
        results = search_service.semantic_search(
            query="test",
            knowledge_base_id=kb_id,
            top_k=5
        )

        print(f"=== SEARCH RESULT COUNT ===")
        print(f"Returned: {len(results)}")
        for idx, res in enumerate(results):
            print(f"Result #{idx+1}: Score={res.score:.4f}, Payload KB ID={res.payload.get('knowledge_base_id')}, Text snippet: {res.payload.get('text')[:50]}...")

        assert len(results) > 0, "Search returned 0 results!"
        print("SUCCESS: Vector search returned > 0 vectors!")

    finally:
        db.close()

if __name__ == "__main__":
    run_qdrant_search_directly()
