"""
test_ai8_phase_c1_postgres.py — Real PostgreSQL Validation for AI-8 Phase C.1 Durable Ledger.

Exercises the schema, migration upgrade, all 6 DB constraints, unique idempotency,
ON DELETE RESTRICT, and migration downgrade directly against a live PostgreSQL instance
in an isolated temporary schema.
"""

import os
import pytest
import psycopg2
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import importlib.util
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "ai8_phase_c1_usage_ledger.py"
)
_spec = importlib.util.spec_from_file_location("ai8_phase_c1_usage_ledger", str(_MIGRATION_PATH))
_migration_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_mod)
upgrade = _migration_mod.upgrade
downgrade = _migration_mod.downgrade

PG_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:nawaz@localhost:5432/arabiq_platform")


def test_postgresql_real_validation():
    """Validates AI-8 Phase C.1 schema and migration against real PostgreSQL in an isolated schema."""
    engine = sa.create_engine(PG_URL, isolation_level="AUTOCOMMIT")

    schema_name = "ai8_c1_pg_validation"

    with engine.connect() as conn:
        # 1. Setup isolated test schema
        conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;"))
        conn.execute(sa.text(f"CREATE SCHEMA {schema_name};"))
        conn.execute(sa.text(f"SET search_path TO {schema_name}, public;"))

        # Create parent tables in isolated schema for foreign keys
        conn.execute(sa.text("""
            CREATE TABLE organizations (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) NOT NULL UNIQUE,
                is_active BOOLEAN DEFAULT TRUE,
                is_deleted BOOLEAN DEFAULT FALSE
            );
        """))
        conn.execute(sa.text("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE
            );
        """))
        conn.execute(sa.text("INSERT INTO organizations (id, name, slug) VALUES (1, 'PG Org 1', 'pg-org-1');"))
        conn.execute(sa.text("INSERT INTO users (id, email) VALUES (1, 'user@example.com');"))

        # 2. Apply migration upgrade() in isolated PostgreSQL schema
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            upgrade()

        # 3. Inspect table, columns, and constraints in PostgreSQL
        insp = sa.inspect(conn)
        tables = insp.get_table_names(schema=schema_name)
        assert "ai_usage_events" in tables, "Table ai_usage_events not found in PostgreSQL!"

        cols = {c["name"]: c for c in insp.get_columns("ai_usage_events", schema=schema_name)}
        assert "idempotency_key" in cols
        assert "total_tokens" in cols

        # Verify Foreign Key ON DELETE RESTRICT on organization_id
        fks = insp.get_foreign_keys("ai_usage_events", schema=schema_name)
        org_fk = next(fk for fk in fks if fk["constrained_columns"] == ["organization_id"])
        # In PostgreSQL / SQLAlchemy inspect, ondelete for RESTRICT is 'RESTRICT' or 'NO ACTION'
        assert org_fk.get("options", {}).get("ondelete") in ["RESTRICT", "NO ACTION"]

        # Verify Indexes
        indexes = {ix["name"]: ix for ix in insp.get_indexes("ai_usage_events", schema=schema_name)}
        assert "ix_ai_usage_events_uuid" in indexes
        assert indexes["ix_ai_usage_events_uuid"]["unique"] is True
        assert "ix_ai_usage_events_idempotency_key" in indexes
        assert indexes["ix_ai_usage_events_idempotency_key"]["unique"] is True
        assert "ix_ai_usage_events_org_created_at" in indexes
        assert "ix_ai_usage_events_org_event_type_created_at" in indexes

        # 4. Insert valid rows in PostgreSQL
        # 4a. Exact quota-bearing
        conn.execute(sa.text("""
            INSERT INTO ai_usage_events (
                uuid, idempotency_key, organization_id, user_id, event_type,
                is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
            ) VALUES (
                gen_random_uuid(), 'pg-exact-1', 1, 1, 'RAG_ASK',
                true, 'EXACT', 50, 150, 200, true
            );
        """))

        # 4b. Unavailable quota-bearing
        conn.execute(sa.text("""
            INSERT INTO ai_usage_events (
                uuid, idempotency_key, organization_id, user_id, event_type,
                is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
            ) VALUES (
                gen_random_uuid(), 'pg-unavail-1', 1, 1, 'RAG_STREAM',
                true, 'UNAVAILABLE', NULL, NULL, NULL, false
            );
        """))

        # 4c. Internal non-quota event
        conn.execute(sa.text("""
            INSERT INTO ai_usage_events (
                uuid, idempotency_key, organization_id, user_id, event_type,
                is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
            ) VALUES (
                gen_random_uuid(), 'pg-internal-1', 1, 1, 'QUERY_EXPANSION',
                false, 'EXACT', 20, 30, 50, true
            );
        """))

        # 4d. Platform event with NULL org
        conn.execute(sa.text("""
            INSERT INTO ai_usage_events (
                uuid, idempotency_key, organization_id, user_id, event_type,
                is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
            ) VALUES (
                gen_random_uuid(), 'pg-platform-1', NULL, NULL, 'WARMUP',
                false, 'EXACT', 10, 10, 20, true
            );
        """))

        # 5. Exercise PostgreSQL DB Constraints
        # 5a. Negative token rejection
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-neg-tokens', 1, 'RAG_ASK',
                    true, 'EXACT', -5, 10, 5, true
                );
            """))

        # 5b. Inconsistent total tokens
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-bad-sum', 1, 'RAG_ASK',
                    true, 'EXACT', 10, 20, 999, true
                );
            """))

        # 5c. Bidirectional: RAG with is_quota_bearing = False must fail!
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-rag-nonquota', 1, 'RAG_ASK',
                    false, 'EXACT', 10, 20, 30, true
                );
            """))

        # 5d. Bidirectional: Internal with is_quota_bearing = True must fail!
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-internal-quota', 1, 'QUERY_EXPANSION',
                    true, 'EXACT', 10, 20, 30, true
                );
            """))

        # 5e. Quota-bearing event without organization_id must fail!
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-quota-no-org', NULL, 'RAG_ASK',
                    true, 'EXACT', 10, 20, 30, true
                );
            """))

        # 5f. Unavailable event with tokens must fail!
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-unavail-with-tokens', 1, 'RAG_ASK',
                    true, 'UNAVAILABLE', 0, NULL, NULL, false
                );
            """))

        # 5g. Duplicate idempotency_key must fail!
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                INSERT INTO ai_usage_events (
                    uuid, idempotency_key, organization_id, event_type,
                    is_quota_bearing, status, prompt_tokens, completion_tokens, total_tokens, is_exact
                ) VALUES (
                    gen_random_uuid(), 'pg-exact-1', 1, 'RAG_ASK',
                    true, 'EXACT', 50, 150, 200, true
                );
            """))

        # 5h. Hard delete of organization referenced by usage event must fail (RESTRICT)!
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("DELETE FROM organizations WHERE id = 1;"))

        # 6. Apply migration downgrade() cleanly
        with Operations.context(ctx):
            downgrade()

        # Verify table is dropped in PostgreSQL (re-inspect connection to avoid cache)
        insp_after = sa.inspect(conn)
        tables_after = insp_after.get_table_names(schema=schema_name)
        assert "ai_usage_events" not in tables_after, "Table was not dropped during downgrade!"

        # 7. Clean up isolated schema
        conn.execute(sa.text(f"DROP SCHEMA {schema_name} CASCADE;"))
