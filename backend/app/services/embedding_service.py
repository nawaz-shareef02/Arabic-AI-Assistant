import logging
from typing import List

import torch
from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Enterprise Embedding Service

    Responsibilities:
    - Load embedding model once
    - Generate embeddings for one or many texts
    - Return embedding dimension
    """

    _model = None

    def __init__(self):
        if EmbeddingService._model is None:
            self._load_model()

    def _load_model(self):
        """
        Load SentenceTransformer only once.
        """

        if (
            settings.EMBEDDING_DEVICE.lower() == "auto"
            and torch.cuda.is_available()
        ):
            device = "cuda"
        else:
            device = "cpu"

        logger.info("=" * 60)
        logger.info("Loading Embedding Model...")
        logger.info(f"Model  : {settings.EMBEDDING_MODEL}")
        logger.info(f"Device : {device}")

        EmbeddingService._model = SentenceTransformer(
            settings.EMBEDDING_MODEL,
            device=device,
        )

        logger.info("Embedding model loaded successfully.")
        logger.info("=" * 60)

    @property
    def model(self):
        return EmbeddingService._model

    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        """

        vector = self.model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        """

        vectors = self.model.encode(
            texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        return vectors.tolist()

    def get_dimension(self) -> int:
        """
        Return embedding dimension.
        """

        return self.model.get_embedding_dimension()

    def is_loaded(self) -> bool:
        return EmbeddingService._model is not None