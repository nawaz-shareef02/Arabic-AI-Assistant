"""
ConversationService — Conversation Lifecycle Management.

Single Responsibility: conversation CRUD, metadata, history retrieval.
This service MUST NOT contain any AI logic (no LLM calls, no embeddings).
AI concerns are delegated to QueryRewriterService and TitleService.
"""

import math
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.crud.conversation import ConversationRepository
from app.crud.message import MessageRepository
from app.models.conversation import Conversation, ConversationStatus
from app.models.message import Message
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
)

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Manages conversation lifecycle: create, read, update, delete, search.

    Architecture
    ------------
    - Uses Repository Pattern (ConversationRepository, MessageRepository).
    - All DB access is delegated; no raw SQLAlchemy queries here.
    - No AI logic — LLM calls belong in QueryRewriterService / TitleService.
    - No embeddings — vector search belongs in RAGService.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._conv_repo = ConversationRepository(db)
        self._msg_repo = MessageRepository(db)

    # ──────────────────────────────────────────────────────────────────────
    # Create
    # ──────────────────────────────────────────────────────────────────────

    def create_conversation(
        self,
        user_id: int,
        payload: ConversationCreate,
    ) -> ConversationResponse:
        """Create a new ACTIVE conversation for the given user."""
        conv = self._conv_repo.create(
            user_id=user_id,
            knowledge_base_id=payload.knowledge_base_id,
            title=payload.title,
        )
        logger.info(
            f"AUDIT | Action: conversation_created | "
            f"User: {user_id} | Conversation: {conv.id}"
        )
        return self._to_response(conv)

    # ──────────────────────────────────────────────────────────────────────
    # Read
    # ──────────────────────────────────────────────────────────────────────

    def list_conversations(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 30,
        search: Optional[str] = None,
        status: Optional[str] = None,
        knowledge_base_id: Optional[int] = None,
        sort_by: str = "last_message_at",
    ) -> ConversationListResponse:
        """Return a paginated, filterable list of conversations for the sidebar."""
        conversations, total = self._conv_repo.list_by_user(
            user_id=user_id,
            page=page,
            page_size=page_size,
            search=search,
            status=status,
            knowledge_base_id=knowledge_base_id,
            sort_by=sort_by,
        )
        pages = math.ceil(total / page_size) if page_size > 0 else 1

        responses = []
        for conv in conversations:
            r = self._to_response(conv)
            r.message_count = self._conv_repo.count_messages(conv.id)
            responses.append(r)

        return ConversationListResponse(
            conversations=responses,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def get_conversation(
        self, conversation_id: int, user_id: int
    ) -> Optional[Conversation]:
        """Return the full conversation ORM object (with messages lazy-loaded)."""
        return self._conv_repo.get_by_id_and_user(conversation_id, user_id)

    def get_history(
        self,
        conversation_id: int,
        token_budget: int,
    ) -> List[Message]:
        """Return recent messages within the token budget (for RAGService)."""
        return self._msg_repo.get_history(
            conversation_id, token_budget=token_budget
        )

    # ──────────────────────────────────────────────────────────────────────
    # Update
    # ──────────────────────────────────────────────────────────────────────

    def update_conversation(
        self,
        conversation_id: int,
        user_id: int,
        payload: ConversationUpdate,
    ) -> Optional[ConversationResponse]:
        """Rename, archive, pin, or change status of a conversation."""
        conv = self._conv_repo.get_by_id_and_user(conversation_id, user_id)
        if conv is None:
            return None

        # Validate status value.
        if payload.status is not None:
            try:
                ConversationStatus(payload.status.upper())
            except ValueError:
                raise ValueError(
                    f"Invalid status '{payload.status}'. "
                    f"Valid values: ACTIVE, ARCHIVED, DELETED"
                )

        updated = self._conv_repo.update(
            conv,
            title=payload.title,
            status=payload.status.upper() if payload.status else None,
            is_pinned=payload.is_pinned,
        )
        logger.info(
            f"AUDIT | Action: conversation_updated | "
            f"User: {user_id} | Conversation: {conversation_id} | Payload: {payload}"
        )
        return self._to_response(updated)

    def set_title_if_empty(
        self,
        conversation_id: int,
        title: str,
    ) -> None:
        """
        Set the title only if it hasn't been set yet.
        Called by TitleService after generating a title from the first message.
        Idempotent — safe to call multiple times.
        """
        conv = self._conv_repo.get_by_id(conversation_id)
        if conv and not conv.title:
            self._conv_repo.update_title(conv, title)

    def touch_last_message_at(self, conversation_id: int) -> None:
        """Update last_message_at — called after each successful exchange."""
        conv = self._conv_repo.get_by_id(conversation_id)
        if conv:
            self._conv_repo.touch_last_message_at(conv)

    # ──────────────────────────────────────────────────────────────────────
    # Delete
    # ──────────────────────────────────────────────────────────────────────

    def delete_conversation(
        self, conversation_id: int, user_id: int
    ) -> bool:
        """Soft-delete (status → DELETED). Returns True if found and deleted."""
        conv = self._conv_repo.get_by_id_and_user(conversation_id, user_id)
        if conv is None:
            return False
        self._conv_repo.soft_delete(conv)
        logger.info(
            f"AUDIT | Action: conversation_deleted | "
            f"User: {user_id} | Conversation: {conversation_id}"
        )
        return True

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _to_response(self, conv: Conversation) -> ConversationResponse:
        return ConversationResponse(
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
            message_count=0,  # Populated by list_conversations only.
        )
