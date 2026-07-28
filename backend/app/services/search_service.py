from sqlalchemy.orm import Session

from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService


class SearchService:
    """
    Enterprise Semantic Search Service.

    Uses singleton EmbeddingService and QdrantService so no heavy objects
    are re-instantiated per request.
    """

    def __init__(self, db: Session):
        self.db = db
        # Both constructors return singleton-backed instances — no re-initialization.
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    def semantic_search(
        self,
        query: str,
        knowledge_base_id: int,
        top_k: int = 5,
    ):

        results = self.qdrant_service.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            limit=top_k,
        )

        return results