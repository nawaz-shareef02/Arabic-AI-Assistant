import pytest
from unittest.mock import MagicMock, patch
from app.services.search_service import SearchService


def test_semantic_search():
    """Test SearchService.semantic_search with mocked vector search results."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [(1,)]
    mock_point = MagicMock()
    mock_point.id = 1
    mock_point.score = 0.95
    mock_point.payload = {"text": "Saudi Vision 2030 content", "chunk_uuid": "abc-123"}

    with patch("app.services.search_service.QdrantService") as mock_qdrant_cls:
        mock_qdrant_svc = mock_qdrant_cls.return_value
        mock_qdrant_svc.search.return_value = [mock_point]

        service = SearchService(mock_db)
        results = service.semantic_search(
            query="What is Saudi Vision 2030?",
            knowledge_base_id=5,
            organization_id=1,
        )

        assert len(results) == 1
        assert results[0].score == 0.95