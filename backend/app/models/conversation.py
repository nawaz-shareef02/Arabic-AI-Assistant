import enum
import uuid as py_uuid
import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.organization import Organization
    from app.models.knowledge_base import KnowledgeBase
    from app.models.message import Message


class ConversationStatus(str, enum.Enum):
    """
    Conversation lifecycle status.

    Uses a single status column instead of multiple boolean flags to keep
    the data model clean and mutually exclusive.

    ACTIVE   — Default; visible in the user's conversation list.
    ARCHIVED — Hidden from main list; recoverable.
    DELETED  — Soft-deleted; excluded from all user-facing queries.
    """

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class Conversation(Base):
    """
    Persistent conversation session between a user and a knowledge base.

    Relationships
    -------------
    User (1) → Conversation (N) → Message (N)
    KnowledgeBase (1) → Conversation (N)

    Indexing strategy
    -----------------
    - user_id + status: drives the sidebar list (most common query)
    - last_message_at DESC: drives ordering (newest conversation first)
    - knowledge_base_id: optional filter in the sidebar
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        default=1,
        server_default="1",
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Single status column — avoids duplicate boolean flag anti-pattern.
    status: Mapped[str] = mapped_column(
        String(20),
        default=ConversationStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )

    # is_pinned is orthogonal to status — a pinned conversation can be ACTIVE or ARCHIVED.
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_message_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ────────────────────────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="conversations",
        foreign_keys=[organization_id],
    )
    user: Mapped["User"] = relationship(
        back_populates="conversations",
        foreign_keys=[user_id],
    )
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        back_populates="conversations",
    )
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="select",
    )
