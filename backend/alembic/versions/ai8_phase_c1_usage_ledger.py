"""ai8_phase_c1_usage_ledger

AI-8 Phase C.1 — Durable PostgreSQL AI Usage Ledger.

Creates ai_usage_events table for authoritative token and quota accounting.
Enforces non-negative token counts, exact vs unavailable token semantics,
quota-bearing tenant attribution, and idempotency uniqueness boundaries.

Revision ID: ai8_phase_c1_usage_ledger
Revises: ai8_phase_b_quota_policy
Create Date: 2026-09-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "ai8_phase_c1_usage_ledger"
down_revision: Union[str, Sequence[str], None] = "ai8_phase_b_quota_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("uuid", UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("is_quota_bearing", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(20), nullable=False, server_default="EXACT"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("is_exact", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('EXACT', 'UNAVAILABLE')",
            name="ck_ai_usage_events_status",
        ),
        sa.CheckConstraint(
            "event_type IN ('RAG_ASK', 'RAG_STREAM', 'RAG_CONV_ASK', 'RAG_CONV_STREAM', 'QUERY_REWRITE', 'QUERY_EXPANSION', 'TITLE_GENERATION', 'EVALUATION', 'WARMUP')",
            name="ck_ai_usage_events_event_type",
        ),
        sa.CheckConstraint(
            "NOT is_quota_bearing OR organization_id IS NOT NULL",
            name="ck_ai_usage_events_quota_org",
        ),
        sa.CheckConstraint(
            "(is_quota_bearing AND event_type IN ('RAG_ASK', 'RAG_STREAM', 'RAG_CONV_ASK', 'RAG_CONV_STREAM')) OR "
            "(NOT is_quota_bearing AND event_type NOT IN ('RAG_ASK', 'RAG_STREAM', 'RAG_CONV_ASK', 'RAG_CONV_STREAM'))",
            name="ck_ai_usage_events_quota_types",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "status != 'UNAVAILABLE' OR ("
            "prompt_tokens IS NULL AND "
            "completion_tokens IS NULL AND "
            "total_tokens IS NULL AND "
            "NOT is_exact"
            ")",
            name="ck_ai_usage_events_unavailable_tokens",
        ),
    )

    # Unique Indexes
    op.create_index("ix_ai_usage_events_uuid", "ai_usage_events", ["uuid"], unique=True)
    op.create_index("ix_ai_usage_events_idempotency_key", "ai_usage_events", ["idempotency_key"], unique=True)

    # Filtering & Access Pattern Indexes
    op.create_index("ix_ai_usage_events_organization_id", "ai_usage_events", ["organization_id"])
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])
    op.create_index("ix_ai_usage_events_request_id", "ai_usage_events", ["request_id"])
    op.create_index("ix_ai_usage_events_event_type", "ai_usage_events", ["event_type"])
    op.create_index("ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"])
    op.create_index("ix_ai_usage_events_org_created_at", "ai_usage_events", ["organization_id", "created_at"])
    op.create_index(
        "ix_ai_usage_events_org_event_type_created_at",
        "ai_usage_events",
        ["organization_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("ai_usage_events")
