"""s14_2_org_mgmt_audit

Sprint 14.2 — Enterprise Organization Management & Audit Logging Schema.

Creates organization_invitations and audit_logs tables.
Adds quota and soft delete columns to organizations table.

Revision ID: s14_2_org_mgmt_audit
Revises: s14_enterprise_rbac
Create Date: 2026-07-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON


# revision identifiers, used by Alembic.
revision: str = "s14_2_org_mgmt_audit"
down_revision: Union[str, Sequence[str], None] = "s14_enterprise_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add quota and soft delete columns to organizations
    op.add_column("organizations", sa.Column("max_users", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("max_workspaces", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("max_knowledge_bases", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("max_storage_mb", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("max_documents", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("organizations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("deleted_by_id", sa.Integer(), nullable=True))

    # 2. Create organization_invitations table
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("uuid", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_organization_invitations_uuid", "organization_invitations", ["uuid"])
    op.create_index("ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"])
    op.create_index("ix_organization_invitations_email", "organization_invitations", ["email"])
    op.create_index("ix_organization_invitations_token_hash", "organization_invitations", ["token_hash"])

    # 3. Create audit_logs table (Refinement #5 & #8)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("uuid", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="System"),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("http_method", sa.String(10), nullable=True),
        sa.Column("api_endpoint", sa.String(255), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="success"),
        sa.Column("metadata_json", JSON(), nullable=True),
    )
    op.create_index("ix_audit_logs_uuid", "audit_logs", ["uuid"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])

    # Composite Indices (Refinement #8)
    op.create_index("ix_audit_logs_org_ts", "audit_logs", ["organization_id", "timestamp"])
    op.create_index("ix_audit_logs_user_ts", "audit_logs", ["user_id", "timestamp"])
    op.create_index("ix_audit_logs_action_ts", "audit_logs", ["action", "timestamp"])
    op.create_index("ix_audit_logs_res_ts", "audit_logs", ["resource_type", "timestamp"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("organization_invitations")
    op.drop_column("organizations", "deleted_by_id")
    op.drop_column("organizations", "deleted_at")
    op.drop_column("organizations", "is_deleted")
    op.drop_column("organizations", "max_documents")
    op.drop_column("organizations", "max_storage_mb")
    op.drop_column("organizations", "max_knowledge_bases")
    op.drop_column("organizations", "max_workspaces")
    op.drop_column("organizations", "max_users")
