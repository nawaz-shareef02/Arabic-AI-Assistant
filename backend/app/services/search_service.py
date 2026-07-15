from sqlalchemy.orm import Session

from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService


class SearchService:
    """
    Enterprise Semantic Search Service
    """

    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    def semantic_search(
        self,
        query: str,
        knowledge_base_id: int,
        top_k: int = 5,
    ):

        print("=" * 60)
        print("SEARCH SERVICE")
        print("Query:", query)
        print("KB:", knowledge_base_id)
        print("Top K:", top_k)
        print("=" * 60)

        results = self.qdrant_service.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            limit=top_k,
        )

        print("Returned:", len(results))
        print("=" * 60)

        return results