"""s15_2_invitation_hardening

Sprint 15.2 — Enterprise Invitation Hardening Schema Migration.

Adds accepted_at, revoked_at, updated_at columns and composite status index
to organization_invitations table for high-throughput lifecycle tracking.

Revision ID: s15_2_invitation_hardening
Revises: s15_1_multitenancy
Create Date: 2026-08-21
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s15_2_invitation_hardening"
down_revision: Union[str, Sequence[str], None] = "s15_1_multitenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add timestamp tracking columns to organization_invitations
    op.add_column(
        "organization_invitations",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organization_invitations",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organization_invitations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )

    # 2. Add composite index for efficient pending invitation lookup by org & status
    op.create_index(
        "ix_org_invitations_org_status",
        "organization_invitations",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_org_invitations_org_status", table_name="organization_invitations")
    op.drop_column("organization_invitations", "updated_at")
    op.drop_column("organization_invitations", "revoked_at")
    op.drop_column("organization_invitations", "accepted_at")
