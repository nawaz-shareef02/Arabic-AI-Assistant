"""ai8_phase_b_quota_policy

AI-8 Phase B — Organization Monthly AI Token Budget Schema Migration.

Adds monthly_token_budget column to organizations table with non-negative check constraint.
Existing quota limits (max_storage_mb, max_documents) are preserved.

Revision ID: ai8_phase_b_quota_policy
Revises: s15_3_db_optimization
Create Date: 2026-09-27
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ai8_phase_b_quota_policy"
down_revision: Union[str, Sequence[str], None] = "s15_3_db_optimization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "monthly_token_budget",
            sa.BigInteger(),
            sa.CheckConstraint(
                "monthly_token_budget >= 0",
                name="ck_org_monthly_token_budget_non_negative",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "monthly_token_budget")
