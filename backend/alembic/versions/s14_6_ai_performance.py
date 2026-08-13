"""s14_6_ai_performance

Sprint 14.6 — Enterprise AI Performance Monitoring & Optimization Schema.

Creates ai_benchmark_runs table for benchmark versioning, evaluation profiles,
Executive AI Scorecards, and regression tracking.

Revision ID: s14_6_ai_performance
Revises: s14_4_security_hardening
Create Date: 2026-07-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON


# revision identifiers, used by Alembic.
revision: str = "s14_6_ai_performance"
down_revision: Union[str, Sequence[str], None] = "s14_4_security_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_benchmark_runs",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("uuid", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("dataset_version", sa.String(50), nullable=False, server_default="1.0.0"),
        sa.Column("benchmark_version", sa.String(50), nullable=False, server_default="1.0.0"),
        sa.Column("pipeline_version", sa.String(50), nullable=False, server_default="14.6.0"),
        sa.Column("profile_name", sa.String(50), nullable=False, server_default="Standard"),
        sa.Column("metrics_json", JSON(), nullable=True),
        sa.Column("scorecard_json", JSON(), nullable=True),
        sa.Column("recommendations_json", JSON(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_benchmark_runs_uuid", "ai_benchmark_runs", ["uuid"])
    op.create_index("ix_ai_benchmark_runs_dataset_ver", "ai_benchmark_runs", ["dataset_version"])
    op.create_index("ix_ai_benchmark_runs_profile", "ai_benchmark_runs", ["profile_name"])
    op.create_index("ix_ai_benchmark_runs_created_at", "ai_benchmark_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_benchmark_runs")
