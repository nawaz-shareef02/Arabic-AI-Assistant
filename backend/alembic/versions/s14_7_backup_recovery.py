"""s14_7_backup_recovery

Sprint 14.7 — Enterprise Backup, Disaster Recovery & High Availability Schema.

Creates backup_records table for manifest file tracking, SHA-256 checksums,
immutable locking, legal hold, and RTO/RPO SLA metrics.

Revision ID: s14_7_backup_recovery
Revises: s14_6_ai_performance
Create Date: 2026-07-29
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON


# revision identifiers, used by Alembic.
revision: str = "s14_7_backup_recovery"
down_revision: Union[str, Sequence[str], None] = "s14_6_ai_performance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backup_records",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("uuid", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("backup_type", sa.String(50), nullable=False, server_default="Full"),
        sa.Column("target", sa.String(100), nullable=False, server_default="All"),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("manifest_path", sa.String(500), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(50), nullable=False, server_default="completed"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rto_seconds", sa.Float(), nullable=False, server_default="120.0"),
        sa.Column("rpo_seconds", sa.Float(), nullable=False, server_default="60.0"),
        sa.Column("manifest_json", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_backup_records_uuid", "backup_records", ["uuid"])
    op.create_index("ix_backup_records_type", "backup_records", ["backup_type"])
    op.create_index("ix_backup_records_status", "backup_records", ["status"])
    op.create_index("ix_backup_records_created_at", "backup_records", ["created_at"])


def downgrade() -> None:
    op.drop_table("backup_records")
