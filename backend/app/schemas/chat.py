from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):

    question: str = Field(
        ...,
        min_length=2,
        max_length=5000,
    )

    knowledge_base_id: int

    # Optional — when provided, activates the conversational RAG pipeline
    # and persists messages to the database.
    # When absent, the stateless (original) pipeline runs unchanged.
    conversation_id: Optional[int] = None


class SourceResponse(BaseModel):

    score: float

    chunk_uuid: str

    parsed_document_id: int


class ChatResponse(BaseModel):

    answer: str

    sources: list[SourceResponse]