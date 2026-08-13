import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.services.embedding_service import EmbeddingService


def test_embedding_service():
    """Test EmbeddingService embed_text and embed_batch with mocked model."""
    mock_model = MagicMock()
    mock_model.encode.side_effect = lambda texts, **kw: (
        np.array([0.1] * 384) if isinstance(texts, str)
        else np.array([[0.1] * 384 for _ in texts])
    )
    mock_model.get_embedding_dimension.return_value = 384

    with patch.object(EmbeddingService, "_model", mock_model):
        service = EmbeddingService()
        assert service.is_loaded() is True
        assert service.get_dimension() == 384

        vec = service.embed_text("ArabIQ test")
        assert len(vec) == 384

        batch = service.embed_batch(["AI", "NLP"])
        assert len(batch) == 2