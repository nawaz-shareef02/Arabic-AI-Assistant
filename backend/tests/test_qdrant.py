import pytest
from unittest.mock import MagicMock, patch
from app.services.qdrant_service import QdrantService


def test_qdrant_service_initialization():
    """Test QdrantService initializes collection using mocked client."""
    mock_client = MagicMock()
    mock_client.get_collections.return_value.collections = []

    with patch("app.services.qdrant_service.QdrantClient", return_value=mock_client):
        with patch.object(QdrantService, "_client", mock_client):
            service = QdrantService()
            service.create_collection()
            mock_client.create_collection.assert_called_once()