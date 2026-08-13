"""add_search_vector_to_document_chunks

Sprint 12 — PostgreSQL Full-Text Search support.

Adds a tsvector column with GIN index and auto-update trigger to
document_chunks for enterprise keyword retrieval.

Revision ID: s12_add_search_vector
Revises: a1b2c3d4e5f6
Create Date: 2026-07-28

Changes:
  1. Add `search_vector` column (TSVECTOR, nullable)
  2. Create GIN index for fast full-text search
  3. Backfill existing rows from chunk_text
  4. Create trigger to auto-populate on INSERT/UPDATE of chunk_text

Rollback:
  Drops trigger, function, index, and column cleanly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = "s12_add_search_vector"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add search_vector column
    op.add_column(
        "document_chunks",
        sa.Column("search_vector", TSVECTOR, nullable=True),
    )

    # 2. Create GIN index for fast full-text search
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )

    # 3. Backfill existing rows — populates search_vector from chunk_text.
    #    Uses the 'simple' text search config (language-agnostic tokenization)
    #    which works reliably for both Arabic and English text.
    op.execute(
        """
        UPDATE document_chunks
        SET search_vector = to_tsvector('simple', COALESCE(chunk_text, ''))
        """
    )

    # 4. Create trigger function to auto-update search_vector
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_chunk_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', COALESCE(NEW.chunk_text, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 5. Attach trigger to document_chunks table
    op.execute(
        """
        CREATE TRIGGER trg_chunk_search_vector
        BEFORE INSERT OR UPDATE OF chunk_text
        ON document_chunks
        FOR EACH ROW
        EXECUTE FUNCTION update_chunk_search_vector();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_chunk_search_vector ON document_chunks"
    )
    op.execute("DROP FUNCTION IF EXISTS update_chunk_search_vector()")
    op.drop_index(
        "ix_document_chunks_search_vector", table_name="document_chunks"
    )
    op.drop_column("document_chunks", "search_vector")
