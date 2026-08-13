import pytest
from app.services.chunk_service import ChunkService


def test_chunk_splitting():
    """Test ChunkService splits text into expected chunks."""
    sample_text = (
        "Artificial Intelligence is transforming enterprise software. "
        * 50
    )
    service = ChunkService()
    chunks = service.split_text(sample_text)

    assert len(chunks) > 0
    first_chunk = chunks[0]
    assert "chunk_index" in first_chunk
    assert "chunk_text" in first_chunk
    assert first_chunk["char_count"] > 0