"""
test_ai8_phase_c1_ledger.py — Comprehensive Test Suite for AI-8 Phase C.1 Durable Usage Ledger.

Tests:
1. Exact usage event persistence and token accounting
2. Unavailable usage event persistence and NULL-token contract
3. Quota-bearing event requires organization attribution
4. Internal non-quota event persistence with optional org observability
5. Platform event with nullable organization (WARMUP, EVALUATION)
6. Negative token count rejection (DB check constraint + Repo)
7. Total token sum consistency rejection (DB check constraint + Repo)
8. Duplicate event / idempotency boundary rejection (DB unique constraint + Repo)
9. Alembic migration upgrade
10. Alembic migration downgrade
11. Organization and date query index behavior & monthly aggregation
12. Repository persistence, lookups (id, uuid, idempotency_key), and summary
"""

import datetime
import uuid as py_uuid
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.database.base import Base
from app.models.organization import Organization
from app.models.ai_usage_event import (
    AIUsageEvent,
    AIUsageEventType,
    AIUsageStatus,
    QUOTA_BEARING_EVENT_TYPES,
)
from app.repositories.ai_usage_repository import (
    AIUsageRepository,
    DuplicateUsageEventError,
)
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


@pytest.fixture
def db_session():
    """Provides an isolated in-memory SQLite database session for ledger tests."""
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Pre-create test organizations
    org1 = Organization(name="Test Org 1", slug="test-org-1", is_active=True)
    org2 = Organization(name="Test Org 2", slug="test-org-2", is_active=True)
    session.add_all([org1, org2])
    session.commit()

    try:
        yield session
    finally:
        session.close()


# ===========================================================================
# 1. EXACT USAGE EVENT
# ===========================================================================

class TestExactUsageEvent:
    def test_exact_event_persists_authoritative_tokens(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        event = repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="idemp-exact-1",
            organization_id=1,
            request_id="req-123",
            correlation_id="corr-456",
            status=AIUsageStatus.EXACT,
            prompt_tokens=45,
            completion_tokens=150,
        )

        assert event.id is not None
        assert event.uuid is not None
        assert event.idempotency_key == "idemp-exact-1"
        assert event.organization_id == 1
        assert event.request_id == "req-123"
        assert event.correlation_id == "corr-456"
        assert event.event_type == "RAG_ASK"
        assert event.is_quota_bearing is True
        assert event.status == "EXACT"
        assert event.prompt_tokens == 45
        assert event.completion_tokens == 150
        assert event.total_tokens == 195
        assert event.is_exact is True
        assert event.created_at is not None

    def test_orm_model_exact_event_persists(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-exact-raw",
            organization_id=1,
            event_type="RAG_STREAM",
            is_quota_bearing=True,
            status="EXACT",
            prompt_tokens=30,
            completion_tokens=70,
            total_tokens=100,
            is_exact=True,
        )
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)

        assert event.id is not None
        assert event.total_tokens == 100


# ===========================================================================
# 2. UNAVAILABLE USAGE EVENT
# ===========================================================================

class TestUnavailableUsageEvent:
    def test_unavailable_event_persists_null_tokens(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        event = repo.create_event(
            event_type=AIUsageEventType.RAG_STREAM,
            idempotency_key="idemp-unavail-1",
            organization_id=1,
            request_id="req-unavail-1",
            status=AIUsageStatus.UNAVAILABLE,
        )

        assert event.id is not None
        assert event.status == "UNAVAILABLE"
        assert event.prompt_tokens is None
        assert event.completion_tokens is None
        assert event.total_tokens is None
        assert event.is_exact is False

    def test_unavailable_event_with_tokens_rejected_by_repo(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="UNAVAILABLE usage events must not record token counts"):
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-unavail-bad",
                organization_id=1,
                status=AIUsageStatus.UNAVAILABLE,
                prompt_tokens=0,  # 0 tokens != unavailable! Must be NULL
            )

    def test_unavailable_event_with_tokens_rejected_by_db_constraint(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-unavail-db-bad",
            organization_id=1,
            event_type="RAG_ASK",
            is_quota_bearing=True,
            status="UNAVAILABLE",
            prompt_tokens=10,  # Invalid: UNAVAILABLE requires prompt_tokens IS NULL
            is_exact=False,
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_unavailable_event_cannot_claim_is_exact(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-unavail-masquerade",
            organization_id=1,
            event_type="RAG_ASK",
            is_quota_bearing=True,
            status="UNAVAILABLE",
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            is_exact=True,  # Invalid: cannot claim is_exact=True when UNAVAILABLE
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ===========================================================================
# 3. QUOTA-BEARING REQUIRES ORGANIZATION
# ===========================================================================

class TestQuotaBearingRequiresOrganization:
    def test_quota_bearing_without_org_rejected_by_repo(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="Quota-bearing AI usage events require an organization_id"):
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-no-org-1",
                organization_id=None,
                prompt_tokens=10,
                completion_tokens=20,
            )

    def test_quota_bearing_without_org_rejected_by_db_constraint(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-no-org-db",
            organization_id=None,  # Violates ck_ai_usage_events_quota_org
            event_type="RAG_ASK",
            is_quota_bearing=True,
            status="EXACT",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            is_exact=True,
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ===========================================================================
# 4. INTERNAL NON-QUOTA EVENTS
# ===========================================================================

class TestInternalNonQuotaEvents:
    @pytest.mark.parametrize(
        "internal_type",
        [
            AIUsageEventType.QUERY_REWRITE,
            AIUsageEventType.QUERY_EXPANSION,
            AIUsageEventType.TITLE_GENERATION,
        ],
    )
    def test_internal_events_persisted_with_org_observability(
        self, db_session: Session, internal_type: AIUsageEventType
    ):
        repo = AIUsageRepository(db_session)
        event = repo.create_event(
            event_type=internal_type,
            idempotency_key=f"idemp-{internal_type.value}-1",
            organization_id=1,  # Retained for tenant observability
            status=AIUsageStatus.EXACT,
            prompt_tokens=15,
            completion_tokens=25,
        )

        assert event.id is not None
        assert event.event_type == internal_type.value
        assert event.is_quota_bearing is False  # Automatically non-quota
        assert event.organization_id == 1
        assert event.total_tokens == 40

    def test_internal_event_cannot_be_marked_quota_bearing(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="cannot be marked quota-bearing"):
            repo.create_event(
                event_type=AIUsageEventType.QUERY_EXPANSION,
                idempotency_key="idemp-expansion-quota-bad",
                organization_id=1,
                is_quota_bearing=True,  # Prohibited by policy
                prompt_tokens=10,
                completion_tokens=10,
            )

    def test_internal_event_quota_bearing_rejected_by_db_constraint(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-expansion-db-bad",
            organization_id=1,
            event_type="QUERY_EXPANSION",
            is_quota_bearing=True,  # Violates ck_ai_usage_events_quota_types
            status="EXACT",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            is_exact=True,
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_rag_event_cannot_be_marked_non_quota_bearing_by_repo(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="must be quota-bearing"):
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-rag-nonquota-bad",
                organization_id=1,
                is_quota_bearing=False,  # Prohibited by bidirectional policy
                prompt_tokens=10,
                completion_tokens=10,
            )

    def test_rag_event_non_quota_rejected_by_db_constraint(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-rag-db-nonquota-bad",
            organization_id=1,
            event_type="RAG_ASK",
            is_quota_bearing=False,  # Violates ck_ai_usage_events_quota_types
            status="EXACT",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            is_exact=True,
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ===========================================================================
# 5. PLATFORM EVENTS WITH NULLABLE ORGANIZATION
# ===========================================================================

class TestPlatformEventsNullableOrganization:
    @pytest.mark.parametrize(
        "platform_type",
        [AIUsageEventType.WARMUP, AIUsageEventType.EVALUATION],
    )
    def test_platform_event_persists_with_null_org(
        self, db_session: Session, platform_type: AIUsageEventType
    ):
        repo = AIUsageRepository(db_session)
        event = repo.create_event(
            event_type=platform_type,
            idempotency_key=f"idemp-{platform_type.value}-null-org",
            organization_id=None,  # Platform event has no tenant
            status=AIUsageStatus.EXACT,
            prompt_tokens=50,
            completion_tokens=100,
        )

        assert event.id is not None
        assert event.organization_id is None
        assert event.is_quota_bearing is False
        assert event.total_tokens == 150


# ===========================================================================
# 6. NEGATIVE TOKEN REJECTION
# ===========================================================================

class TestNegativeTokenRejection:
    def test_negative_prompt_tokens_rejected_by_repo(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="non-negative"):
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-neg-prompt",
                organization_id=1,
                prompt_tokens=-5,
                completion_tokens=10,
            )

    def test_negative_completion_tokens_rejected_by_repo(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="non-negative"):
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-neg-comp",
                organization_id=1,
                prompt_tokens=10,
                completion_tokens=-1,
            )

    def test_negative_tokens_rejected_by_db_constraint(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-neg-db",
            organization_id=1,
            event_type="RAG_ASK",
            is_quota_bearing=True,
            status="EXACT",
            prompt_tokens=-10,
            completion_tokens=20,
            total_tokens=10,
            is_exact=True,
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ===========================================================================
# 7. TOTAL TOKEN CONSISTENCY
# ===========================================================================

class TestTotalTokenConsistency:
    def test_inconsistent_total_tokens_rejected_by_repo(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        with pytest.raises(ValueError, match="Inconsistent total_tokens"):
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-inconsistent-repo",
                organization_id=1,
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=50,  # Inconsistent: 10 + 20 != 50
            )

    def test_inconsistent_total_tokens_rejected_by_db_constraint(self, db_session: Session):
        event = AIUsageEvent(
            idempotency_key="idemp-inconsistent-db",
            organization_id=1,
            event_type="RAG_ASK",
            is_quota_bearing=True,
            status="EXACT",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=99,  # Violates ck_ai_usage_events_exact_tokens
            is_exact=True,
        )
        db_session.add(event)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ===========================================================================
# 8. DUPLICATE EVENT / IDEMPOTENCY BOUNDARY
# ===========================================================================

class TestDuplicateEventIdempotency:
    def test_duplicate_idempotency_key_raises_duplicate_error(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        event1 = repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="idemp-unique-boundary-1",
            organization_id=1,
            prompt_tokens=20,
            completion_tokens=40,
        )
        assert event1.id is not None

        # Replay / retry with identical idempotency_key must raise DuplicateUsageEventError
        with pytest.raises(DuplicateUsageEventError) as exc_info:
            repo.create_event(
                event_type=AIUsageEventType.RAG_ASK,
                idempotency_key="idemp-unique-boundary-1",
                organization_id=1,
                prompt_tokens=20,
                completion_tokens=40,
            )
        assert exc_info.value.idempotency_key == "idemp-unique-boundary-1"

    def test_db_enforces_idempotency_key_uniqueness(self, db_session: Session):
        event1 = AIUsageEvent(
            idempotency_key="idemp-db-uq-key",
            organization_id=1,
            event_type="RAG_ASK",
            is_quota_bearing=True,
            status="EXACT",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            is_exact=True,
        )
        db_session.add(event1)
        db_session.commit()

        event2 = AIUsageEvent(
            idempotency_key="idemp-db-uq-key",  # Duplicate key
            organization_id=1,
            event_type="RAG_STREAM",
            is_quota_bearing=True,
            status="EXACT",
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
            is_exact=True,
        )
        db_session.add(event2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ===========================================================================
# 9 & 10. MIGRATION UPGRADE & DOWNGRADE
# ===========================================================================

class TestMigrationLifecycle:
    def test_migration_upgrade_and_downgrade_cleanly(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                # 1. Upgrade
                upgrade()
            conn.commit()

            # Verify table was created with expected columns
            insp = sa.inspect(conn)
            tables = insp.get_table_names()
            assert "ai_usage_events" in tables

            cols = {c["name"]: c for c in insp.get_columns("ai_usage_events")}
            required_cols = [
                "id", "uuid", "idempotency_key", "organization_id", "user_id",
                "request_id", "correlation_id", "event_type", "is_quota_bearing",
                "status", "prompt_tokens", "completion_tokens", "total_tokens",
                "is_exact", "created_at"
            ]
            for col_name in required_cols:
                assert col_name in cols, f"Column '{col_name}' missing in migrated schema."

            indexes = [ix["name"] for ix in insp.get_indexes("ai_usage_events")]
            assert "ix_ai_usage_events_uuid" in indexes
            assert "ix_ai_usage_events_idempotency_key" in indexes
            assert "ix_ai_usage_events_organization_id" in indexes
            assert "ix_ai_usage_events_org_created_at" in indexes
            assert "ix_ai_usage_events_org_event_type_created_at" in indexes

            # 2. Downgrade
            with Operations.context(ctx):
                downgrade()
            conn.commit()

            insp_after = sa.inspect(conn)
            assert "ai_usage_events" not in insp_after.get_table_names()


# ===========================================================================
# 11. ORGANIZATION & DATE QUERY INDEX BEHAVIOR & AGGREGATIONS
# ===========================================================================

class TestOrganizationDateQueryBehavior:
    def test_monthly_usage_sum_aggregates_exact_quota_bearing_tokens_only(
        self, db_session: Session
    ):
        repo = AIUsageRepository(db_session)
        now = datetime.datetime.now(datetime.timezone.utc)
        start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_month = (start_month + datetime.timedelta(days=32)).replace(day=1)

        # 1. Org 1: Quota-bearing exact event (should count)
        repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="agg-org1-rag1",
            organization_id=1,
            prompt_tokens=100,
            completion_tokens=200,  # 300 total
        )

        # 2. Org 1: Another quota-bearing exact event (should count)
        repo.create_event(
            event_type=AIUsageEventType.RAG_CONV_STREAM,
            idempotency_key="agg-org1-rag2",
            organization_id=1,
            prompt_tokens=50,
            completion_tokens=150,  # 200 total
        )

        # 3. Org 1: Internal non-quota event (must NOT count towards monthly budget)
        repo.create_event(
            event_type=AIUsageEventType.QUERY_EXPANSION,
            idempotency_key="agg-org1-internal",
            organization_id=1,
            prompt_tokens=40,
            completion_tokens=60,  # 100 total, is_quota_bearing=False
        )

        # 4. Org 1: Unavailable event (must NOT count)
        repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="agg-org1-unavail",
            organization_id=1,
            status=AIUsageStatus.UNAVAILABLE,
        )

        # 5. Org 2: Quota-bearing event for different tenant (must NOT count for Org 1)
        repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="agg-org2-rag",
            organization_id=2,
            prompt_tokens=1000,
            completion_tokens=2000,  # 3000 total
        )

        # Calculate monthly sum for Org 1
        sum_org1 = repo.get_monthly_usage_sum(
            organization_id=1,
            start_date=start_month,
            end_date=end_month,
        )
        assert sum_org1 == 500  # 300 + 200 = 500

        # Calculate monthly sum for Org 2
        sum_org2 = repo.get_monthly_usage_sum(
            organization_id=2,
            start_date=start_month,
            end_date=end_month,
        )
        assert sum_org2 == 3000

        # Check summary breakdown for Org 1
        summary = repo.get_organization_usage_summary(
            organization_id=1,
            start_date=start_month,
            end_date=end_month,
        )
        assert summary["total_tokens"] == 500
        assert summary["prompt_tokens"] == 150
        assert summary["completion_tokens"] == 350
        assert summary["exact_events_count"] == 2
        assert summary["unavailable_events_count"] == 1


# ===========================================================================
# 12. REPOSITORY PERSISTENCE & RETRIEVAL LOOKUPS
# ===========================================================================

class TestRepositoryLookups:
    def test_repository_lookups_and_pagination(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        created = repo.create_event(
            event_type=AIUsageEventType.RAG_CONV_ASK,
            idempotency_key="lookup-key-1",
            organization_id=1,
            request_id="req-lookup",
            correlation_id="corr-lookup",
            prompt_tokens=25,
            completion_tokens=75,
        )

        # 1. Lookup by ID
        by_id = repo.get_by_id(created.id)
        assert by_id is not None
        assert by_id.id == created.id
        assert by_id.idempotency_key == "lookup-key-1"

        # 2. Lookup by UUID
        by_uuid = repo.get_by_uuid(created.uuid)
        assert by_uuid is not None
        assert by_uuid.id == created.id

        # 3. Lookup by UUID str
        by_uuid_str = repo.get_by_uuid(str(created.uuid))
        assert by_uuid_str is not None
        assert by_uuid_str.id == created.id

        # 4. Lookup by Idempotency Key
        by_key = repo.get_by_idempotency_key("lookup-key-1")
        assert by_key is not None
        assert by_key.id == created.id

        # 5. List with filters
        events, total = repo.list_events(organization_id=1, event_type="RAG_CONV_ASK")
        assert total >= 1
        assert any(e.id == created.id for e in events)

    def test_create_event_with_commit_false(self, db_session: Session):
        repo = AIUsageRepository(db_session)
        event = repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="rollback-test-key",
            organization_id=1,
            prompt_tokens=10,
            completion_tokens=20,
            commit=False,
        )
        assert event.id is not None  # ID generated by flush
        # Roll back transaction
        db_session.rollback()

        # Record should not be present
        lookup = repo.get_by_idempotency_key("rollback-test-key")
        assert lookup is None


# ===========================================================================
# 13. ORGANIZATION FOREIGN KEY LIFECYCLE (RESTRICT VS SOFT DELETE)
# ===========================================================================

class TestOrganizationForeignKeyLifecycle:
    def test_hard_delete_org_with_usage_events_fails_fk_restrict(self, db_session: Session):
        """Hard deleting an organization with historical AI usage events must be blocked by ON DELETE RESTRICT."""
        repo = AIUsageRepository(db_session)
        org = Organization(name="Audit Protected Org", slug="audit-protected-org", is_active=True)
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        # Record usage event
        repo.create_event(
            event_type=AIUsageEventType.RAG_ASK,
            idempotency_key="org-restrict-test-1",
            organization_id=org.id,
            prompt_tokens=10,
            completion_tokens=20,
        )

        # Attempt hard delete of organization
        db_session.delete(org)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # Historical event remains intact and untouched
        event = repo.get_by_idempotency_key("org-restrict-test-1")
        assert event is not None
        assert event.organization_id == org.id

    def test_soft_delete_org_preserves_historical_usage_events(self, db_session: Session):
        """Soft deleting an organization (is_deleted=True) safely preserves historical usage events."""
        repo = AIUsageRepository(db_session)
        org = Organization(name="Soft Deletable Org", slug="soft-deletable-org", is_active=True)
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        repo.create_event(
            event_type=AIUsageEventType.RAG_STREAM,
            idempotency_key="org-soft-delete-test-1",
            organization_id=org.id,
            prompt_tokens=25,
            completion_tokens=50,
        )

        # Perform soft delete as done in OrganizationService
        org.is_deleted = True
        org.is_active = False
        org.deleted_at = datetime.datetime.now(datetime.timezone.utc)
        db_session.commit()

        # Historical event is still accessible and associated with the org
        event = repo.get_by_idempotency_key("org-soft-delete-test-1")
        assert event is not None
        assert event.organization_id == org.id
        assert event.total_tokens == 75
