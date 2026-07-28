import uuid
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    """Payload to create a new conversation."""

    knowledge_base_id: int
    title: Optional[str] = Field(None, max_length=255)


class ConversationUpdate(BaseModel):
    """Payload to partially update a conversation (rename / archive / pin)."""

    title: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, description="ACTIVE | ARCHIVED | DELETED")
    is_pinned: Optional[bool] = None


class ConversationResponse(BaseModel):
    """API representation of a single conversation (without messages)."""

    id: int
    uuid: uuid.UUID
    title: Optional[str]
    user_id: int
    knowledge_base_id: int
    status: str
    is_pinned: bool
    last_message_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""

    conversations: List[ConversationResponse]
    total: int
    page: int
    page_size: int
    pages: int
