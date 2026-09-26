"""
test_ai8_phase_b_quota_policy.py — AI-8 Phase B Quota Policy & Schema Test Suite

Verifies all 8 required Phase B criteria:
1. monthly_token_budget accepts valid integer
2. negative monthly token budget rejected (ORM, DB CheckConstraint, Pydantic)
3. nullable monthly token budget behaves according to chosen unlimited semantics (None = unlimited)
4. existing max_storage_mb behavior remains compatible (persists int, None, rejects negative)
5. existing max_documents behavior remains compatible (persists int, None, rejects negative)
6. migration applies successfully (adds column, activates non-negative check constraint)
7. migration downgrade succeeds (drops column cleanly)
8. repository create & update_quotas methods persist and query quotas cleanly
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.database.base import Base
from app.models.organization import Organization
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationQuotaPolicy, OrganizationQuotaUpdate

import importlib.util
from pathlib import Path

_MIGRATION_PATH = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "ai8_phase_b_quota_policy.py"
_spec = importlib.util.spec_from_file_location("ai8_phase_b_quota_policy", str(_MIGRATION_PATH))
_migration_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_mod)
upgrade = _migration_mod.upgrade
downgrade = _migration_mod.downgrade



@pytest.fixture
def db_session():
    """Provides an isolated in-memory SQLite database session for model tests."""
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ===========================================================================
# 1. MONTHLY_TOKEN_BUDGET ACCEPTS VALID INTEGER
# ===========================================================================

class TestMonthlyTokenBudgetValidInteger:
    def test_monthly_token_budget_persists_valid_integer(self, db_session: Session):
        org = Organization(
            name="Enterprise Alpha",
            slug="enterprise-alpha",
            monthly_token_budget=1_000_000,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.id is not None
        assert org.monthly_token_budget == 1_000_000

    def test_pydantic_schema_accepts_valid_budget(self):
        policy = OrganizationQuotaPolicy(monthly_token_budget=500_000)
        assert policy.monthly_token_budget == 500_000

        update = OrganizationQuotaUpdate(monthly_token_budget=25_000_000)
        assert update.monthly_token_budget == 25_000_000


# ===========================================================================
# 2. NEGATIVE MONTHLY TOKEN BUDGET REJECTED
# ===========================================================================

class TestNegativeMonthlyTokenBudgetRejected:
    def test_orm_validator_rejects_negative_budget(self):
        with pytest.raises(ValueError, match="monthly_token_budget must be a non-negative integer"):
            Organization(
                name="Invalid Org",
                slug="invalid-org",
                monthly_token_budget=-500,
            )

    def test_orm_attribute_assignment_rejects_negative(self, db_session: Session):
        org = Organization(name="Valid Org", slug="valid-org", monthly_token_budget=100)
        db_session.add(org)
        db_session.commit()

        with pytest.raises(ValueError, match="monthly_token_budget must be a non-negative integer"):
            org.monthly_token_budget = -1

    def test_pydantic_schema_rejects_negative_budget(self):
        with pytest.raises(ValidationError):
            OrganizationQuotaPolicy(monthly_token_budget=-10)

        with pytest.raises(ValidationError):
            OrganizationQuotaUpdate(monthly_token_budget=-1)


# ===========================================================================
# 3. NULLABLE / UNLIMITED SEMANTICS
# ===========================================================================

class TestUnlimitedSemantics:
    def test_monthly_token_budget_defaults_to_none_unlimited(self, db_session: Session):
        org = Organization(name="Unlimited Org", slug="unlimited-org")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.monthly_token_budget is None

    def test_explicit_none_persists_as_unlimited(self, db_session: Session):
        org = Organization(
            name="Explicit None Org",
            slug="explicit-none-org",
            monthly_token_budget=None,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.monthly_token_budget is None

    def test_pydantic_schema_defaults_to_none(self):
        policy = OrganizationQuotaPolicy()
        assert policy.monthly_token_budget is None
        assert policy.max_storage_mb is None
        assert policy.max_documents is None


# ===========================================================================
# 4. EXISTING MAX_STORAGE_MB COMPATIBILITY
# ===========================================================================

class TestMaxStorageMbCompatibility:
    def test_max_storage_mb_persists_valid_integer(self, db_session: Session):
        org = Organization(
            name="Storage Org",
            slug="storage-org",
            max_storage_mb=10240,  # 10 GB
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.max_storage_mb == 10240

    def test_max_storage_mb_accepts_none_for_unlimited(self, db_session: Session):
        org = Organization(
            name="Unlimited Storage",
            slug="unlimited-storage",
            max_storage_mb=None,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.max_storage_mb is None

    def test_max_storage_mb_rejects_negative(self):
        with pytest.raises(ValueError, match="max_storage_mb must be a non-negative integer"):
            Organization(name="Bad Storage", slug="bad-storage", max_storage_mb=-100)

        with pytest.raises(ValidationError):
            OrganizationQuotaPolicy(max_storage_mb=-50)


# ===========================================================================
# 5. EXISTING MAX_DOCUMENTS COMPATIBILITY
# ===========================================================================

class TestMaxDocumentsCompatibility:
    def test_max_documents_persists_valid_integer(self, db_session: Session):
        org = Organization(
            name="Docs Org",
            slug="docs-org",
            max_documents=5000,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.max_documents == 5000

    def test_max_documents_accepts_none_for_unlimited(self, db_session: Session):
        org = Organization(
            name="Unlimited Docs",
            slug="unlimited-docs",
            max_documents=None,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        assert org.max_documents is None

    def test_max_documents_rejects_negative(self):
        with pytest.raises(ValueError, match="max_documents must be a non-negative integer"):
            Organization(name="Bad Docs", slug="bad-docs", max_documents=-1)

        with pytest.raises(ValidationError):
            OrganizationQuotaPolicy(max_documents=-1)


# ===========================================================================
# 6. MIGRATION APPLIES SUCCESSFULLY
# ===========================================================================

class TestMigrationUpgrade:
    def test_migration_upgrade_adds_column_and_enforces_constraint(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(sa.text(
                "CREATE TABLE organizations ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR(255) NOT NULL, "
                "slug VARCHAR(100) NOT NULL UNIQUE, "
                "max_storage_mb INTEGER NULL, "
                "max_documents INTEGER NULL"
                ")"
            ))
            conn.commit()

            # Execute migration upgrade
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                upgrade()
            conn.commit()

            # Verify column added
            insp = sa.inspect(conn)
            cols = [c["name"] for c in insp.get_columns("organizations")]
            assert "monthly_token_budget" in cols

            # Verify accepts positive and NULL
            conn.execute(sa.text("INSERT INTO organizations (id, name, slug, monthly_token_budget) VALUES (1, 'Org 1', 'org-1', 1000)"))
            conn.execute(sa.text("INSERT INTO organizations (id, name, slug, monthly_token_budget) VALUES (2, 'Org 2', 'org-2', NULL)"))
            conn.commit()

            # Verify check constraint rejects negative value
            with pytest.raises(IntegrityError):
                conn.execute(sa.text("INSERT INTO organizations (id, name, slug, monthly_token_budget) VALUES (3, 'Org 3', 'org-3', -50)"))
                conn.commit()


# ===========================================================================
# 7. MIGRATION DOWNGRADE SUCCEEDS
# ===========================================================================

class TestMigrationDowngrade:
    def test_migration_downgrade_drops_column_cleanly(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(sa.text(
                "CREATE TABLE organizations ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR(255) NOT NULL, "
                "slug VARCHAR(100) NOT NULL UNIQUE"
                ")"
            ))
            conn.commit()

            # Upgrade
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                upgrade()
            conn.commit()

            insp_up = sa.inspect(conn)
            assert "monthly_token_budget" in [c["name"] for c in insp_up.get_columns("organizations")]

            # Downgrade
            with Operations.context(ctx):
                downgrade()
            conn.commit()

            insp_down = sa.inspect(conn)
            assert "monthly_token_budget" not in [c["name"] for c in insp_down.get_columns("organizations")]


# ===========================================================================
# 8. REPOSITORY INTEGRATION & BACKWARD COMPATIBILITY
# ===========================================================================

class TestOrganizationRepositoryQuotas:
    def test_repo_create_with_quotas(self, db_session: Session):
        repo = OrganizationRepository(db_session)
        org = repo.create(
            name="Acme Corp",
            slug="acme-corp",
            monthly_token_budget=5_000_000,
            max_storage_mb=50000,
            max_documents=10000,
        )

        assert org.id is not None
        assert org.monthly_token_budget == 5_000_000
        assert org.max_storage_mb == 50000
        assert org.max_documents == 10000

    def test_repo_create_defaults_unlimited_backward_compatible(self, db_session: Session):
        repo = OrganizationRepository(db_session)
        # Calling without quota arguments must remain backward compatible
        org = repo.create(name="Legacy Org", slug="legacy-org")

        assert org.id is not None
        assert org.monthly_token_budget is None
        assert org.max_storage_mb is None
        assert org.max_documents is None

    def test_repo_update_quotas(self, db_session: Session):
        repo = OrganizationRepository(db_session)
        org = repo.create(name="Updatable Org", slug="updatable-org")
        assert org.monthly_token_budget is None

        updated = repo.update_quotas(
            org_id=org.id,
            monthly_token_budget=2_000_000,
            max_storage_mb=20000,
            max_documents=500,
        )

        assert updated is not None
        assert updated.monthly_token_budget == 2_000_000
        assert updated.max_storage_mb == 20000
        assert updated.max_documents == 500
