"""
AIUsageEvent Model — Authoritative Durable PostgreSQL AI Usage Ledger.

Frozen Accounting Policy (AI-8):
- Exactly ONE durable usage ledger: ai_usage_events.
- Quota-bearing events: RAG_ASK, RAG_STREAM, RAG_CONV_ASK, RAG_CONV_STREAM (is_quota_bearing=True).
- Internal/system events: QUERY_REWRITE, QUERY_EXPANSION, TITLE_GENERATION, EVALUATION, WARMUP (is_quota_bearing=False).
- Source of truth: OllamaProvider -> TokenUsage -> ai_usage_events.
- Status: EXACT (authoritative tokens) vs UNAVAILABLE (never masquerades as zero).
- DB invariants: Non-negative tokens, exact token sum consistency, quota-bearing org presence, unique idempotency.
"""

import enum
import uuid as py_uuid
import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class AIUsageEventType(str, enum.Enum):
    """
    Frozen AI usage event classifications.
    Quota-bearing: RAG_ASK, RAG_STREAM, RAG_CONV_ASK, RAG_CONV_STREAM
    Non-quota internal: QUERY_REWRITE, QUERY_EXPANSION, TITLE_GENERATION, EVALUATION, WARMUP
    """
    RAG_ASK = "RAG_ASK"
    RAG_STREAM = "RAG_STREAM"
    RAG_CONV_ASK = "RAG_CONV_ASK"
    RAG_CONV_STREAM = "RAG_CONV_STREAM"
    QUERY_REWRITE = "QUERY_REWRITE"
    QUERY_EXPANSION = "QUERY_EXPANSION"
    TITLE_GENERATION = "TITLE_GENERATION"
    EVALUATION = "EVALUATION"
    WARMUP = "WARMUP"


QUOTA_BEARING_EVENT_TYPES = frozenset({
    AIUsageEventType.RAG_ASK,
    AIUsageEventType.RAG_STREAM,
    AIUsageEventType.RAG_CONV_ASK,
    AIUsageEventType.RAG_CONV_STREAM,
    "RAG_ASK",
    "RAG_STREAM",
    "RAG_CONV_ASK",
    "RAG_CONV_STREAM",
})


class AIUsageStatus(str, enum.Enum):
    """
    Accounting status of an AI usage record.
    EXACT: authoritative terminal token counts measured from provider.
    UNAVAILABLE: token usage was not reported or unavailable; never masquerades as zero tokens.
    """
    EXACT = "EXACT"
    UNAVAILABLE = "UNAVAILABLE"


class AIUsageEvent(Base):
    """
    Authoritative durable PostgreSQL ledger for AI token usage accounting.
    Enforces exactness, tenant attribution, non-negative invariants, and duplicate settlement prevention.
    """
    __tablename__ = "ai_usage_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(160),
        unique=True,
        index=True,
        nullable=False,
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    is_quota_bearing: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=AIUsageStatus.EXACT.value,
        nullable=False,
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    completion_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    total_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    is_exact: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship()
    user: Mapped[Optional["User"]] = relationship()

    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "status IN ('EXACT', 'UNAVAILABLE')",
            name="ck_ai_usage_events_status",
        ),
        CheckConstraint(
            "event_type IN ('RAG_ASK', 'RAG_STREAM', 'RAG_CONV_ASK', 'RAG_CONV_STREAM', 'QUERY_REWRITE', 'QUERY_EXPANSION', 'TITLE_GENERATION', 'EVALUATION', 'WARMUP')",
            name="ck_ai_usage_events_event_type",
        ),
        CheckConstraint(
            "NOT is_quota_bearing OR organization_id IS NOT NULL",
            name="ck_ai_usage_events_quota_org",
        ),
        CheckConstraint(
            "(is_quota_bearing AND event_type IN ('RAG_ASK', 'RAG_STREAM', 'RAG_CONV_ASK', 'RAG_CONV_STREAM')) OR "
            "(NOT is_quota_bearing AND event_type NOT IN ('RAG_ASK', 'RAG_STREAM', 'RAG_CONV_ASK', 'RAG_CONV_STREAM'))",
            name="ck_ai_usage_events_quota_types",
        ),
        CheckConstraint(
            "status != 'EXACT' OR ("
            "prompt_tokens IS NOT NULL AND "
            "completion_tokens IS NOT NULL AND "
            "total_tokens IS NOT NULL AND "
            "prompt_tokens >= 0 AND "
            "completion_tokens >= 0 AND "
            "total_tokens = prompt_tokens + completion_tokens AND "
            "is_exact"
            ")",
            name="ck_ai_usage_events_exact_tokens",
        ),
        CheckConstraint(
            "status != 'UNAVAILABLE' OR ("
            "prompt_tokens IS NULL AND "
            "completion_tokens IS NULL AND "
            "total_tokens IS NULL AND "
            "NOT is_exact"
            ")",
            name="ck_ai_usage_events_unavailable_tokens",
        ),
        Index("ix_ai_usage_events_org_created_at", "organization_id", "created_at"),
        Index("ix_ai_usage_events_org_event_type_created_at", "organization_id", "event_type", "created_at"),
    )
