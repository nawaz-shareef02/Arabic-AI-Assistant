"""
Conversation Repository — Repository Pattern.

All database interaction for the conversations table lives here.
No business logic, no AI calls, no external service calls.
"""

import math
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, ConversationStatus


class ConversationRepository:
    """
    Data access layer for Conversation entities.

    All methods accept an SQLAlchemy Session injected from outside
    (Dependency Injection) — no session is created internally.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────
    # Write operations
    # ──────────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        user_id: int,
        knowledge_base_id: int,
        title: Optional[str] = None,
    ) -> Conversation:
        """Create and persist a new conversation."""
        conv = Conversation(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            title=title,
            status=ConversationStatus.ACTIVE.value,
        )
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def update_title(self, conv: Conversation, title: str) -> Conversation:
        """Set the conversation title — only called once (when title is None)."""
        conv.title = title
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def update(
        self,
        conv: Conversation,
        *,
        title: Optional[str] = None,
        status: Optional[str] = None,
        is_pinned: Optional[bool] = None,
    ) -> Conversation:
        """Partial update — only supplied fields are changed."""
        if title is not None:
            conv.title = title
        if status is not None:
            conv.status = status
        if is_pinned is not None:
            conv.is_pinned = is_pinned
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def soft_delete(self, conv: Conversation) -> Conversation:
        """Mark as DELETED (soft delete — data is not purged)."""
        conv.status = ConversationStatus.DELETED.value
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def touch_last_message_at(self, conv: Conversation) -> None:
        """Update last_message_at to now — called after each assistant reply."""
        from sqlalchemy import text
        self.db.execute(
            text(
                "UPDATE conversations SET last_message_at = now() "
                "WHERE id = :id"
            ),
            {"id": conv.id},
        )
        self.db.commit()

    # ──────────────────────────────────────────────────────────────────────
    # Read operations
    # ──────────────────────────────────────────────────────────────────────

    def get_by_id(self, conversation_id: int) -> Optional[Conversation]:
        """Fetch by primary key (no user filter — caller must authorise)."""
        return self.db.get(Conversation, conversation_id)

    def get_by_id_and_user(
        self, conversation_id: int, user_id: int
    ) -> Optional[Conversation]:
        """Fetch only if the conversation belongs to the authenticated user."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.status != ConversationStatus.DELETED.value,
        )
        return self.db.scalars(stmt).first()

    def list_by_user(
        self,
        user_id: int,
        *,
        page: int = 1,
        page_size: int = 30,
        search: Optional[str] = None,
        status: Optional[str] = None,
        knowledge_base_id: Optional[int] = None,
        sort_by: str = "last_message_at",
    ) -> tuple[List[Conversation], int]:
        """
        Return paginated conversations for the sidebar.

        Excludes DELETED conversations by default (pass status="DELETED" to see them).
        Pinned conversations are returned first, then sorted by sort_by DESC.
        """
        stmt = select(Conversation).where(Conversation.user_id == user_id)

        # Status filter — exclude deleted unless explicitly requested.
        if status:
            stmt = stmt.where(Conversation.status == status.upper())
        else:
            stmt = stmt.where(
                Conversation.status != ConversationStatus.DELETED.value
            )

        if knowledge_base_id is not None:
            stmt = stmt.where(Conversation.knowledge_base_id == knowledge_base_id)

        if search:
            stmt = stmt.where(
                Conversation.title.ilike(f"%{search}%")
            )

        # Pinned first, then by requested sort column.
        sort_col = Conversation.last_message_at
        if sort_by == "created_at":
            sort_col = Conversation.created_at
        elif sort_by == "title":
            sort_col = Conversation.title

        stmt = stmt.order_by(
            Conversation.is_pinned.desc(),
            sort_col.desc().nullslast(),
        )

        total: int = self.db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        offset = (page - 1) * page_size
        rows = self.db.scalars(stmt.offset(offset).limit(page_size)).all()
        return list(rows), total

    def count_messages(self, conversation_id: int) -> int:
        """Return the total message count for a single conversation."""
        from app.models.message import Message

        return (
            self.db.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id
                )
            )
            or 0
        )
