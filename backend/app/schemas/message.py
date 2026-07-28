import uuid
from typing import Any, List, Optional
from datetime import datetime

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """API representation of a single chat message."""

    id: int
    conversation_id: int
    role: str
    content: str
    citations: Optional[Any] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationWithMessages(BaseModel):
    """Full conversation detail including ordered message history."""

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
    messages: List[MessageResponse] = []

    model_config = {"from_attributes": True}
