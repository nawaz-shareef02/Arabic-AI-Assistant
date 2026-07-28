from sqlalchemy.orm import Session

from app.models.parsed_document import ParsedDocument
from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService


class IndexingService:
    """
    Responsible for indexing parsed document chunks into Qdrant.
    """

    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    def index_document(
        self,
        parsed_document: ParsedDocument,
        knowledge_base_id: int = None,
    ) -> int:
        """
        Generate embeddings for all chunks and store them in Qdrant.

        Returns:
            int: Number of indexed chunks.
        """

        chunks = parsed_document.chunks

        if not chunks:
            raise ValueError("No document chunks found.")

        # Resolve knowledge_base_id explicitly if not passed
        if knowledge_base_id is None:
            from app.models.document import Document
            doc = self.db.query(Document).filter(Document.id == parsed_document.document_id).first()
            if doc:
                knowledge_base_id = doc.knowledge_base_id
            else:
                raise ValueError(f"Knowledge base ID could not be resolved for ParsedDocument {parsed_document.id}")

        # Extract chunk texts
        texts = [chunk.chunk_text for chunk in chunks]

        # Generate embeddings
        embeddings = self.embedding_service.embed_batch(texts)

        # Store embeddings in Qdrant with explicit knowledge_base_id
        self.qdrant_service.upsert_chunks(
            chunks=chunks,
            embeddings=embeddings,
            knowledge_base_id=knowledge_base_id,
        )

        return len(chunks)