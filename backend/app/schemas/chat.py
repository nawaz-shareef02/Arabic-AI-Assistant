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

    # Optional client-provided idempotency key for durable usage deduplication (AI-8 C.2).
    # Clients may also provide this via the Idempotency-Key or X-Idempotency-Key HTTP headers.
    idempotency_key: Optional[str] = Field(
        None,
        max_length=160,
        description="Optional client idempotency key for duplicate AI usage prevention.",
    )


class SourceResponse(BaseModel):

    score: float

    chunk_uuid: str

    parsed_document_id: int


class ChatResponse(BaseModel):

    answer: str

    sources: list[SourceResponse]