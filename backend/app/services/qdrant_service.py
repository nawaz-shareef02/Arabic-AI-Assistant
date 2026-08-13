import logging
import threading
from typing import List, Optional
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

from app.core.config import settings
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton state — one QdrantClient for the process lifetime.
# ---------------------------------------------------------------------------
_instance: "QdrantService | None" = None
_instance_lock = threading.Lock()
_init_count: int = 0


class QdrantService:
    """
    Enterprise Qdrant Vector Database Service — Singleton Pattern.

    Guarantees:
    - A single QdrantClient is created once and reused across all requests.
    - Thread-safe double-checked locking prevents duplicate construction.
    - Initialization count is logged:
        "QdrantService initialized (1)"   ← correct
        "QdrantService initialized (2)"   ← should never appear.
    """

    # Class-level client cache.
    _client: QdrantClient | None = None

    def __init__(self):
        global _init_count
        # Fast path: client already present.
        if QdrantService._client is not None:
            self.embedding_service = EmbeddingService()
            self.collection_name = settings.QDRANT_COLLECTION
            return

        # Slow path: create client under lock.
        with _instance_lock:
            if QdrantService._client is None:
                _init_count += 1
                QdrantService._client = QdrantClient(
                    host=settings.QDRANT_HOST,
                    port=settings.QDRANT_PORT,
                    check_compatibility=False,
                )
                logger.info(
                    f"QdrantService initialized ({_init_count}) "
                    f"— host={settings.QDRANT_HOST}:{settings.QDRANT_PORT}"
                )

        self.embedding_service = EmbeddingService()
        self.collection_name = settings.QDRANT_COLLECTION

    # Expose client for convenience.
    @property
    def client(self) -> QdrantClient:
        return QdrantService._client  # type: ignore[return-value]

    # --------------------------------------------------
    # Collection
    # --------------------------------------------------

    def create_collection(self):

        collections = self.client.get_collections().collections

        names = [c.name for c in collections]

        if self.collection_name in names:
            logger.info(
                f"Collection '{self.collection_name}' already exists."
            )
            return

        dimension = self.embedding_service.get_dimension()

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=dimension,
                distance=Distance.COSINE,
            ),
        )

        logger.info(
            f"Collection '{self.collection_name}' created."
        )

    # --------------------------------------------------
    # Insert Vectors
    # --------------------------------------------------

    def upsert_chunks(
        self,
        chunks,
        embeddings: List[List[float]],
        knowledge_base_id: int,
        organization_id: Optional[int] = None,
    ):
        if knowledge_base_id is None:
            raise ValueError("knowledge_base_id must be explicitly provided to QdrantService.upsert_chunks")

        points = []

        for chunk, embedding in zip(chunks, embeddings):
            payload = {
                "chunk_uuid": str(chunk.uuid),
                "parsed_document_id": chunk.parsed_document_id,
                "knowledge_base_id": int(knowledge_base_id),
                "chunk_index": chunk.chunk_index,
                "text": chunk.chunk_text,
                "char_count": chunk.char_count,
                "estimated_tokens": chunk.estimated_tokens,
            }
            if organization_id is not None:
                payload["organization_id"] = int(organization_id)

            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=embedding,
                    payload=payload,
                )
            )

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

        logger.info(
            f"{len(points)} vectors indexed into Qdrant for KB {knowledge_base_id} (Org: {organization_id})."
        )

    # --------------------------------------------------
    # Search
    # --------------------------------------------------

    def search(
        self,
        query: Optional[str] = None,
        query_vector: Optional[List[float]] = None,
        knowledge_base_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        limit: Optional[int] = None,
    ):

        if query_vector is None:
            if query is None:
                raise ValueError("Either 'query' or 'query_vector' must be provided.")
            query_vector = self.embedding_service.embed_text(query)

        if limit is None:
            limit = settings.TOP_K_RESULTS

        must_conditions = []
        if organization_id is not None:
            must_conditions.append(
                FieldCondition(
                    key="organization_id",
                    match=MatchValue(value=organization_id),
                )
            )
        if knowledge_base_id is not None:
            must_conditions.append(
                FieldCondition(
                    key="knowledge_base_id",
                    match=MatchValue(value=knowledge_base_id),
                )
            )

        query_filter = Filter(must=must_conditions) if must_conditions else None

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
        )
        return response.points

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------

    def delete_document_vectors(
        self,
        parsed_document_id: int,
    ):

        self.client.delete(

            collection_name=self.collection_name,

            points_selector={

                "filter": {

                    "must": [

                        {

                            "key": "parsed_document_id",

                            "match": {

                                "value": parsed_document_id

                            }

                        }

                    ]

                }

            },

        )

        logger.info(
            f"Vectors removed for ParsedDocument {parsed_document_id}"
        )