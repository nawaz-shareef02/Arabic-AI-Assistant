# pyrefly: ignore-file
import logging
import threading
from typing import List

import torch
from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level initialization counter — proves the model loads exactly once.
# ---------------------------------------------------------------------------
_init_count: int = 0
_load_lock = threading.Lock()


class EmbeddingService:
    """
    Enterprise Embedding Service — Singleton Pattern.

    Guarantees:
    - SentenceTransformer is loaded exactly once for the entire process lifetime.
    - Thread-safe double-checked locking prevents race conditions on startup.
    - Warmup method allows the model to be pre-exercised before traffic hits.
    - Initialization count is logged so operators can verify singleton behaviour:
        "EmbeddingService initialized (1)"   ← correct
        "EmbeddingService initialized (2)"   ← bug; should never appear.
    """

    # Class-level model cache — survives across all instances.
    _model: SentenceTransformer | None = None
    _instance_count: int = 0

    def __init__(self):
        global _init_count
        # Fast path: model already loaded, nothing to do.
        if EmbeddingService._model is not None:
            return

        # Slow path: acquire lock, recheck, then load.
        with _load_lock:
            if EmbeddingService._model is None:
                _init_count += 1
                EmbeddingService._instance_count = _init_count
                self._load_model()
                logger.info(
                    f"EmbeddingService initialized ({EmbeddingService._instance_count}) "
                    f"— model={settings.EMBEDDING_MODEL}"
                )

    # ------------------------------------------------------------------
    # Internal model loader
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Load SentenceTransformer exactly once — never called again after that."""
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

    # ------------------------------------------------------------------
    # Warmup — run a dummy inference so weights are hot before traffic.
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """
        Pre-exercise the model with a trivial inference so that JIT compilation,
        tokenizer initialisation, and any lazy backend allocations happen at
        startup rather than on the first real user request.
        """
        logger.info("EmbeddingService warmup: running dummy inference...")
        _ = self.embed_text("warmup")
        logger.info("EmbeddingService warmup complete.")

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def model(self) -> SentenceTransformer:
        return EmbeddingService._model  # type: ignore[return-value]

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        vector = self.model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        vectors = self.model.encode(
            texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def get_dimension(self) -> int:
        """Return embedding dimension."""
        return self.model.get_embedding_dimension()

    def is_loaded(self) -> bool:
        return EmbeddingService._model is not None