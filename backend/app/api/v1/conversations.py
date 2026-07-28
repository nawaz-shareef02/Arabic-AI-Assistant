"""
Conversations API Router — Sprint 11.

Provides full CRUD for conversation management:
  POST   /conversations                — Create
  GET    /conversations                — List (paginated, filterable)
  GET    /conversations/{id}           — Get with messages
  PATCH  /conversations/{id}           — Rename / Archive / Pin
  DELETE /conversations/{id}           — Soft delete

All endpoints require JWT authentication.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.crud.message import MessageRepository
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
)
from app.schemas.message import ConversationWithMessages, MessageResponse
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/conversations",
    tags=["CONVERSATIONS"],
)


# ──────────────────────────────────────────────────────────────────────────────
# POST /conversations — Create a new conversation
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new conversation linked to a knowledge base.
    The title is optional — TitleService will generate one after the first message.
    """
    svc = ConversationService(db)
    return svc.create_conversation(
        user_id=current_user.id,
        payload=payload,
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /conversations — Paginated list for the sidebar
# ──────────────────────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=ConversationListResponse,
)
def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=255),
    status: Optional[str] = Query(None, description="ACTIVE | ARCHIVED | DELETED"),
    knowledge_base_id: Optional[int] = Query(None),
    sort_by: str = Query("last_message_at", description="last_message_at | created_at | title"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return a paginated list of conversations for the authenticated user.

    - Pinned conversations are always shown first.
    - Sorted by last_message_at DESC by default.
    - Excludes DELETED conversations unless status=DELETED is passed.
    """
    svc = ConversationService(db)
    return svc.list_conversations(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        knowledge_base_id=knowledge_base_id,
        sort_by=sort_by,
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /conversations/{id} — Get conversation with full message history
# ──────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{conversation_id}",
    response_model=ConversationWithMessages,
)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return a single conversation with its full ordered message history.
    Returns 404 if the conversation does not belong to the current user.
    """
    svc = ConversationService(db)
    conv = svc.get_conversation(conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found.",
        )

    msg_repo = MessageRepository(db)
    messages = msg_repo.get_all_for_conversation(conversation_id)

    return ConversationWithMessages(
        id=conv.id,
        uuid=conv.uuid,
        title=conv.title,
        user_id=conv.user_id,
        knowledge_base_id=conv.knowledge_base_id,
        status=conv.status,
        is_pinned=conv.is_pinned,
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                role=m.role,
                content=m.content,
                citations=m.citations,
                prompt_tokens=m.prompt_tokens,
                completion_tokens=m.completion_tokens,
                total_tokens=m.total_tokens,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


# ──────────────────────────────────────────────────────────────────────────────
# PATCH /conversations/{id} — Rename / Archive / Pin
# ──────────────────────────────────────────────────────────────────────────────

@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
def update_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Partially update a conversation.

    Supports:
    - Rename (title)
    - Archive / Restore (status: ACTIVE | ARCHIVED)
    - Pin / Unpin (is_pinned: true | false)
    """
    svc = ConversationService(db)
    try:
        result = svc.update_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found.",
        )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /conversations/{id} — Soft delete
# ──────────────────────────────────────────────────────────────────────────────

@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft-delete a conversation (sets status to DELETED).
    Data is preserved in the database; can be recovered by an admin.
    """
    svc = ConversationService(db)
    deleted = svc.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found.",
        )
