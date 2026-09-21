"""s15_3_database_query_optimization

Sprint 15.3 — Enterprise Database & Query Optimization Migration.

Adds targeted foreign-key and composite indexes to eliminate full table scans,
accelerate filtered sorting, and enforce membership uniqueness.

Revision ID: s15_3_database_query_optimization
Revises: s15_2_invitation_hardening
Create Date: 2026-08-21
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s15_3_db_optimization"
down_revision: Union[str, Sequence[str], None] = "s15_2_invitation_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Documents table: Foreign key index and composite indexes for listing & deduplication
    op.create_index(
        "ix_documents_knowledge_base_id",
        "documents",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_documents_kb_created",
        "documents",
        ["knowledge_base_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_documents_kb_sha256",
        "documents",
        ["knowledge_base_id", "sha256_hash"],
    )

    # 2. KnowledgeBases table: Composite indexes for organization-scoped and user-scoped listing
    op.create_index(
        "ix_kb_org_active_created",
        "knowledge_bases",
        ["organization_id", "is_active", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_kb_owner_active_created",
        "knowledge_bases",
        ["owner_id", "is_active", sa.text("created_at DESC")],
    )

    # 3. Messages table: Composite index for conversation message history
    op.create_index(
        "ix_messages_conv_created",
        "messages",
        ["conversation_id", sa.text("created_at DESC")],
    )

    # 4. OrganizationMembers table: Unique constraint and composite index on (organization_id, user_id)
    op.create_unique_constraint(
        "uq_org_members_org_user",
        "organization_members",
        ["organization_id", "user_id"],
    )

    # 5. DocumentChunks table: Foreign key index on parsed_document_id
    op.create_index(
        "ix_chunks_parsed_doc_id",
        "document_chunks",
        ["parsed_document_id"],
    )

    # 6. SearchAnalytics table: Created_at and Knowledge_base_id indexes
    op.create_index(
        "ix_search_analytics_created",
        "search_analytics",
        ["created_at"],
    )
    op.create_index(
        "ix_search_analytics_kb_id",
        "search_analytics",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_analytics_kb_id", table_name="search_analytics")
    op.drop_index("ix_search_analytics_created", table_name="search_analytics")
    op.drop_index("ix_chunks_parsed_doc_id", table_name="document_chunks")
    op.drop_constraint("uq_org_members_org_user", "organization_members", type_="unique")
    op.drop_index("ix_messages_conv_created", table_name="messages")
    op.drop_index("ix_kb_owner_active_created", table_name="knowledge_bases")
    op.drop_index("ix_kb_org_active_created", table_name="knowledge_bases")
    op.drop_index("ix_documents_kb_sha256", table_name="documents")
    op.drop_index("ix_documents_kb_created", table_name="documents")
    op.drop_index("ix_documents_knowledge_base_id", table_name="documents")
