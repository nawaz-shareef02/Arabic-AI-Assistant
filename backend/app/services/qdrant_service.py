import logging
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


class QdrantService:
    """
    Enterprise Qdrant Vector Database Service
    """

    def __init__(self):

        self.client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            check_compatibility=False,
        )

        self.embedding_service = EmbeddingService()

        self.collection_name = settings.QDRANT_COLLECTION

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
        knowledge_base_id: Optional[int] = None,
    ):

        if knowledge_base_id is None and chunks:
            try:
                first_chunk = chunks[0]
                if (
                    hasattr(first_chunk, "parsed_document")
                    and first_chunk.parsed_document
                    and hasattr(first_chunk.parsed_document, "document")
                    and first_chunk.parsed_document.document
                ):
                    knowledge_base_id = first_chunk.parsed_document.document.knowledge_base_id
            except Exception as e:
                logger.warning(f"Could not resolve knowledge_base_id from chunk: {e}")

        points = []

        for chunk, embedding in zip(chunks, embeddings):

            points.append(

                PointStruct(

                    id=chunk.id,

                    vector=embedding,

                    payload={

                        "chunk_uuid": str(chunk.uuid),

                        "parsed_document_id": chunk.parsed_document_id,

                        "knowledge_base_id": knowledge_base_id,

                        "chunk_index": chunk.chunk_index,

                        "text": chunk.chunk_text,

                        "char_count": chunk.char_count,

                        "estimated_tokens": chunk.estimated_tokens,

                    },

                )

            )

        self.client.upsert(

            collection_name=self.collection_name,

            points=points,

        )

        logger.info(
            f"{len(points)} vectors indexed into Qdrant."
        )

    # --------------------------------------------------
    # Search
    # --------------------------------------------------

    def search(
        self,
        query: Optional[str] = None,
        query_vector: Optional[List[float]] = None,
        knowledge_base_id: Optional[int] = None,
        limit: Optional[int] = None,
    ):

        if query_vector is None:
            if query is None:
                raise ValueError("Either 'query' or 'query_vector' must be provided.")
            query_vector = self.embedding_service.embed_text(query)

        if limit is None:
            limit = settings.TOP_K_RESULTS

        query_filter = None
        if knowledge_base_id is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="knowledge_base_id",
                        match=MatchValue(value=knowledge_base_id),
                    )
                ]
            )

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