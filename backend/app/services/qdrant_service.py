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
    PayloadSchemaType,
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

    def ensure_payload_indexes(self):
        """
        Idempotently ensure required payload indexes exist on the collection.
        Restart-safe and non-destructive:
        - Never deletes the collection.
        - Never recreates the collection.
        - Never deletes or modifies points/vectors.
        - Never changes vector dimension or distance metric.
        """
        try:
            collection_info = self.client.get_collection(self.collection_name)
            existing_schema = collection_info.payload_schema or {}

            indexes_to_create = {
                "organization_id": PayloadSchemaType.INTEGER,
                "knowledge_base_id": PayloadSchemaType.INTEGER,
            }
            for field_name, expected_schema in indexes_to_create.items():
                existing_info = existing_schema.get(field_name)
                if existing_info is not None:
                    existing_type = getattr(existing_info, "data_type", None)
                    if existing_type is None and isinstance(existing_info, dict):
                        existing_type = existing_info.get("data_type")

                    # Check if already indexed with the expected INTEGER schema
                    if existing_type in (expected_schema, expected_schema.value, "integer"):
                        logger.debug(
                            f"Payload index for '{field_name}' (INTEGER) already exists on '{self.collection_name}'."
                        )
                        continue
                    else:
                        logger.info(
                            f"Payload index for '{field_name}' exists with type '{existing_type}', migrating to INTEGER..."
                        )
                        try:
                            self.client.delete_payload_index(
                                collection_name=self.collection_name,
                                field_name=field_name,
                            )
                        except Exception as del_err:
                            logger.warning(
                                f"Could not remove old payload index for '{field_name}': {del_err}"
                            )

                logger.info(
                    f"Creating payload index for '{field_name}' ({expected_schema}) on '{self.collection_name}'..."
                )
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=expected_schema,
                )
                logger.info(f"Payload index for '{field_name}' (INTEGER) verified/created.")
        except Exception as exc:
            logger.warning(f"Payload index check/creation skipped or encountered error: {exc}")

    def create_collection(self):

        collections = self.client.get_collections().collections

        names = [c.name for c in collections]

        if self.collection_name in names:
            logger.info(
                f"Collection '{self.collection_name}' already exists."
            )
            self.ensure_payload_indexes()
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
        self.ensure_payload_indexes()

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

        # AI-3 Enterprise Tenant Boundary Enforcement (Fail-Closed)
        if organization_id is None or knowledge_base_id is None:
            raise ValueError(
                "Tenant boundary missing: Qdrant search requires both 'organization_id' "
                "and 'knowledge_base_id' to enforce fail-closed isolation."
            )

        query_filter = Filter(
            must=[
                FieldCondition(
                    key="organization_id",
                    match=MatchValue(value=organization_id),
                ),
                FieldCondition(
                    key="knowledge_base_id",
                    match=MatchValue(value=knowledge_base_id),
                ),
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
        organization_id: Optional[int] = None,
        knowledge_base_id: Optional[int] = None,
    ) -> bool:
        must_conditions: List[dict] = [
            {
                "key": "parsed_document_id",
                "match": {
                    "value": parsed_document_id
                }
            }
        ]
        if organization_id is not None:
            must_conditions.append({
                "key": "organization_id",
                "match": {"value": organization_id}
            })
        if knowledge_base_id is not None:
            must_conditions.append({
                "key": "knowledge_base_id",
                "match": {"value": knowledge_base_id}
            })

        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector={
                    "filter": {
                        "must": must_conditions
                    }
                },
            )
            logger.info(
                f"Vectors removed for ParsedDocument {parsed_document_id} (Org: {organization_id}, KB: {knowledge_base_id})"
            )
            return True
        except Exception as exc:
            logger.warning(
                f"QdrantService: delete_document_vectors encountered error for ParsedDocument {parsed_document_id}: {exc}"
            )
            return False