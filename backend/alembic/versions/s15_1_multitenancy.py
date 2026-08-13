"""s15_1_multitenancy

Sprint 15.1 — Multi-Tenancy Architecture Schema Migration.

Adds organization_id columns and foreign keys to knowledge_bases and
conversations tables with deterministic non-destructive backfill for existing records.

Revision ID: s15_1_multitenancy
Revises: s14_8_password_reset_token
Create Date: 2026-08-12
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s15_1_multitenancy"
down_revision: Union[str, Sequence[str], None] = "s14_8_password_reset_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable organization_id column to knowledge_bases
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # 2. Add nullable organization_id column to conversations
    op.add_column(
        "conversations",
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # 3. Non-destructive backfill for existing records
    # Assign knowledge_bases.organization_id from owner's organization_membership or default org
    op.execute(
        sa.text(
            "UPDATE knowledge_bases SET organization_id = ("
            "  SELECT organization_id FROM organization_members "
            "  WHERE user_id = knowledge_bases.owner_id LIMIT 1"
            ") WHERE organization_id IS NULL"
        )
    )
    # Fallback to organization ID 1 if owner had no membership record
    op.execute(
        sa.text(
            "UPDATE knowledge_bases SET organization_id = 1 WHERE organization_id IS NULL"
        )
    )

    # Assign conversations.organization_id from parent knowledge_base's organization_id
    op.execute(
        sa.text(
            "UPDATE conversations SET organization_id = ("
            "  SELECT organization_id FROM knowledge_bases "
            "  WHERE id = conversations.knowledge_base_id LIMIT 1"
            ") WHERE organization_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE conversations SET organization_id = 1 WHERE organization_id IS NULL"
        )
    )

    # 4. Alter columns to NOT NULL
    op.alter_column("knowledge_bases", "organization_id", nullable=False)
    op.alter_column("conversations", "organization_id", nullable=False)

    # 5. Create indexes
    op.create_index(
        "ix_knowledge_bases_organization_id", "knowledge_bases", ["organization_id"]
    )
    op.create_index(
        "ix_conversations_organization_id", "conversations", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_organization_id", table_name="conversations")
    op.drop_index("ix_knowledge_bases_organization_id", table_name="knowledge_bases")
    op.drop_column("conversations", "organization_id")
    op.drop_column("knowledge_bases", "organization_id")
