"""s13_knowledge_intelligence

Sprint 13 — Enterprise Knowledge Intelligence Platform schema additions.

Creates document_metadata, document_entities, document_relationships,
and search_analytics tables, and adds classification column to documents.

Revision ID: s13_knowledge_intelligence
Revises: s12_add_search_vector
Create Date: 2026-07-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s13_knowledge_intelligence"
down_revision: Union[str, Sequence[str], None] = "s12_add_search_vector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add classification column to documents table
    op.add_column(
        "documents",
        sa.Column("classification", sa.String(100), server_default="Technical Documentation", nullable=True),
    )

    # 2. Create document_metadata table
    op.create_table(
        "document_metadata",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification", sa.String(100), nullable=False, server_default="Technical Documentation"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_metadata_document_id", "document_metadata", ["document_id"])
    op.create_index("ix_document_metadata_classification", "document_metadata", ["classification"])

    # 3. Create document_entities table
    op.create_table(
        "document_entities",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_text", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="EN"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_entities_document_id", "document_entities", ["document_id"])
    op.create_index("ix_document_entities_entity_text", "document_entities", ["entity_text"])
    op.create_index("ix_document_entities_entity_type", "document_entities", ["entity_type"])

    # 4. Create document_relationships table
    op.create_table(
        "document_relationships",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_relationships_source_document_id", "document_relationships", ["source_document_id"])
    op.create_index("ix_document_relationships_target_document_id", "document_relationships", ["target_document_id"])
    op.create_index("ix_document_relationships_relationship_type", "document_relationships", ["relationship_type"])

    # 5. Create search_analytics table
    op.create_table(
        "search_analytics",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("knowledge_base_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_returned", sa.JSON(), nullable=True),
        sa.Column("filters_used", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_search_analytics_user_id", "search_analytics", ["user_id"])
    op.create_index("ix_search_analytics_knowledge_base_id", "search_analytics", ["knowledge_base_id"])
    op.create_index("ix_search_analytics_created_at", "search_analytics", ["created_at"])


def downgrade() -> None:
    op.drop_table("search_analytics")
    op.drop_table("document_relationships")
    op.drop_table("document_entities")
    op.drop_table("document_metadata")
    op.drop_column("documents", "classification")
