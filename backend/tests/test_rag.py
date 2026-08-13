import pytest
from unittest.mock import MagicMock, patch
from app.services.rag_service import RAGService


def test_rag_service_ask():
    """Test RAGService.ask with mocked search and LLM services."""
    mock_db = MagicMock()

    mock_result = MagicMock()
    mock_result.text = "Saudi Vision 2030 details"
    mock_result.score = 0.9
    mock_result.chunk_uuid = "chunk-1"
    mock_result.parsed_document_id = 10
    mock_result.payload = {"text": "Saudi Vision 2030 details", "chunk_uuid": "chunk-1", "parsed_document_id": 10}

    with patch("app.services.rag_service.SearchService") as mock_search_cls, \
         patch("app.services.rag_service.LLMFactory") as mock_llm_factory:

        mock_search_svc = mock_search_cls.return_value
        mock_search_svc.hybrid_search.return_value = [mock_result]

        mock_llm_provider = MagicMock()
        mock_llm_provider.generate.return_value = "Saudi Vision 2030 is a strategic framework."
        mock_llm_factory.get_provider.return_value = mock_llm_provider

        rag = RAGService(mock_db)
        resp = rag.ask(question="What is Saudi Vision 2030?", knowledge_base_id=5)

        assert resp["answer"] == "Saudi Vision 2030 is a strategic framework."
        assert len(resp["sources"]) == 1
        assert resp["sources"][0]["chunk_uuid"] == "chunk-1"