# pyrefly: ignore [missing-import]
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentChunkResponse(BaseModel):

    uuid: UUID

    chunk_index: int

    chunk_text: str

    char_count: int

    estimated_tokens: int

    start_offset: int

    end_offset: int

    model_config = ConfigDict(
        from_attributes=True
    )