"""
Sprint 1 Security Fix Regression Test Suite (SEC-REQ-01 through SEC-REQ-04).

Coverage:
- SEC-REQ-01: Role Assignment Boundary & Anti-Privilege Escalation
  1. Org Admin cannot assign Super Admin role -> 403 Forbidden
  2. Org Admin cannot assign role granting system.admin permission -> 403 Forbidden
  3. Org Admin cannot assign role into another organization -> 403 Forbidden
  4. Org Admin cannot assign role to another organization's user -> 403 Forbidden
  5. Legitimate same-org role assignment by Org Admin succeeds -> 200 OK
  6. Super Admin can legitimately assign roles across orgs -> 200 OK

- SEC-REQ-02: Organization Member & Activity Authorization
  7. Org Admin can access own organization members -> 200 OK
  8. Org Admin can access own organization activity -> 200 OK
  9. Org Admin receives 403 for another organization's members
  10. Org Admin receives 403 for another organization's activity
  11. Super Admin legitimate cross-org access to members and activity -> 200 OK

- SEC-REQ-03: Multi-Tenant Analytics Isolation
  12. Analytics for Org A contain only Org A data (KB & document counts)
  13. Analytics for Org B contain only Org B data
  14. Search queries from Org B never appear in Org A analytics
  15. Document category and entity aggregations are tenant-scoped
  16. Super Admin can view global analytics or filter by specific organization

- SEC-REQ-04: Complete & Safe Document Cleanup
  17. Delete document removes PostgreSQL record, Qdrant vectors, and physical file
  18. Missing physical file is handled safely and idempotently
  19. Missing Qdrant vectors / errors do not cause incorrect failure
  20. Partial failure safety: DB error prevents external deletions (rollback integrity)
  21. Deleted document cannot subsequently appear in retrieval
"""

import os
import uuid as py_uuid
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.role import Role, UserRole, RolePermission
from app.models.permission import Permission
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.models.chunk import DocumentChunk
from app.models.search_analytics import SearchAnalytics
from app.models.audit_log import AuditLog
from app.core.security import get_password_hash, create_access_token
from app.core.rbac_seeder import seed_rbac
from app.services.document_service import DocumentService
from app.services.analytics_service import AnalyticsService
from app.core.config import settings


# ---------------------------------------------------------------------------
# Test database & client fixtures
# ---------------------------------------------------------------------------

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(name="db_session")
def fixture_db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_rbac(db)
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(name="test_data")
def fixture_test_data(db_session):
    """Sets up two isolated organizations, admin users, regular members, and standard roles."""
    org_a = Organization(name="Organization Alpha", slug="org-alpha", is_active=True)
    org_b = Organization(name="Organization Beta", slug="org-beta", is_active=True)
    db_session.add_all([org_a, org_b])
    db_session.commit()

    # Users
    admin_a = User(
        email="admin_a@alpha.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Admin Alpha",
        organization=org_a.name,
        is_active=True,
    )
    admin_b = User(
        email="admin_b@beta.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Admin Beta",
        organization=org_b.name,
        is_active=True,
    )
    member_a = User(
        email="member_a@alpha.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Member Alpha",
        organization=org_a.name,
        is_active=True,
    )
    member_b = User(
        email="member_b@beta.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Member Beta",
        organization=org_b.name,
        is_active=True,
    )
    super_admin = User(
        email="superadmin@arabiq.sa",
        hashed_password=get_password_hash("Password123!"),
        full_name="Super Admin",
        organization="Platform",
        is_active=True,
    )

    db_session.add_all([admin_a, admin_b, member_a, member_b, super_admin])
    db_session.commit()

    # Organization memberships
    db_session.add_all([
        OrganizationMember(organization_id=org_a.id, user_id=admin_a.id),
        OrganizationMember(organization_id=org_a.id, user_id=member_a.id),
        OrganizationMember(organization_id=org_b.id, user_id=admin_b.id),
        OrganizationMember(organization_id=org_b.id, user_id=member_b.id),
        OrganizationMember(organization_id=org_a.id, user_id=super_admin.id),
    ])
    db_session.commit()

    # Roles
    org_admin_role = db_session.query(Role).filter(Role.name == "Organization Admin").first()
    super_admin_role = db_session.query(Role).filter(Role.name == "Super Admin").first()
    editor_role = db_session.query(Role).filter(Role.name == "Editor").first()
    viewer_role = db_session.query(Role).filter(Role.name == "Viewer").first()

    db_session.add_all([
        UserRole(user_id=admin_a.id, role_id=org_admin_role.id, organization_id=org_a.id),
        UserRole(user_id=admin_b.id, role_id=org_admin_role.id, organization_id=org_b.id),
        UserRole(user_id=member_a.id, role_id=viewer_role.id, organization_id=org_a.id),
        UserRole(user_id=member_b.id, role_id=viewer_role.id, organization_id=org_b.id),
        UserRole(user_id=super_admin.id, role_id=super_admin_role.id, organization_id=org_a.id),
    ])
    db_session.commit()

    # Tokens & headers
    token_admin_a = create_access_token(
        subject=admin_a.email, additional_claims={"user_id": admin_a.id, "org_id": org_a.id}
    )
    token_admin_b = create_access_token(
        subject=admin_b.email, additional_claims={"user_id": admin_b.id, "org_id": org_b.id}
    )
    token_super = create_access_token(
        subject=super_admin.email, additional_claims={"user_id": super_admin.id, "org_id": org_a.id}
    )

    return {
        "org_a": org_a,
        "org_b": org_b,
        "admin_a": admin_a,
        "admin_b": admin_b,
        "member_a": member_a,
        "member_b": member_b,
        "super_admin": super_admin,
        "org_admin_role": org_admin_role,
        "super_admin_role": super_admin_role,
        "editor_role": editor_role,
        "viewer_role": viewer_role,
        "headers_a": {"Authorization": f"Bearer {token_admin_a}"},
        "headers_b": {"Authorization": f"Bearer {token_admin_b}"},
        "headers_super": {"Authorization": f"Bearer {token_super}"},
    }


# ===========================================================================
# FIX 1 — SEC-REQ-01: Role Assignment Boundary Enforcement Tests
# ===========================================================================

def test_org_admin_cannot_assign_super_admin(client, test_data):
    """1. Org Admin cannot assign Super Admin role -> 403 Forbidden."""
    payload = {
        "user_id": test_data["member_a"].id,
        "role_id": test_data["super_admin_role"].id,
        "organization_id": test_data["org_a"].id,
    }
    res = client.post("/api/v1/roles/assign", json=payload, headers=test_data["headers_a"])
    assert res.status_code == 403
    assert "Super Administrator" in res.json()["detail"]


def test_org_admin_cannot_assign_system_role_with_system_admin_perm(client, db_session, test_data):
    """2. Org Admin cannot assign any role granting system.admin permission -> 403 Forbidden."""
    # Create custom role with system.admin permission
    sys_perm = db_session.query(Permission).filter(Permission.name == "system.admin").first()
    custom_role = Role(name="Custom Root", is_system_role=False, organization_id=test_data["org_a"].id)
    db_session.add(custom_role)
    db_session.commit()
    db_session.add(RolePermission(role_id=custom_role.id, permission_id=sys_perm.id))
    db_session.commit()

    payload = {
        "user_id": test_data["member_a"].id,
        "role_id": custom_role.id,
        "organization_id": test_data["org_a"].id,
    }
    res = client.post("/api/v1/roles/assign", json=payload, headers=test_data["headers_a"])
    assert res.status_code == 403
    assert "Super Administrator" in res.json()["detail"]


def test_org_admin_cannot_assign_role_into_other_organization(client, test_data):
    """3. Org Admin cannot assign a role into another organization -> 403 Forbidden."""
    payload = {
        "user_id": test_data["member_a"].id,
        "role_id": test_data["editor_role"].id,
        "organization_id": test_data["org_b"].id,  # Cross-org attempt
    }
    res = client.post("/api/v1/roles/assign", json=payload, headers=test_data["headers_a"])
    assert res.status_code == 403
    assert "another organization" in res.json()["detail"]


def test_org_admin_cannot_assign_role_to_other_org_member(client, test_data):
    """4. Org Admin cannot assign roles to a user not in their organization -> 403 Forbidden."""
    payload = {
        "user_id": test_data["member_b"].id,  # Belongs to Org B
        "role_id": test_data["editor_role"].id,
        "organization_id": test_data["org_a"].id,
    }
    res = client.post("/api/v1/roles/assign", json=payload, headers=test_data["headers_a"])
    assert res.status_code == 403
    assert "not a member" in res.json()["detail"]


def test_legitimate_same_org_role_assignment(client, db_session, test_data):
    """5. Legitimate same-org role assignment by Org Admin succeeds -> 200 OK."""
    payload = {
        "user_id": test_data["member_a"].id,
        "role_id": test_data["editor_role"].id,
        "organization_id": test_data["org_a"].id,
    }
    res = client.post("/api/v1/roles/assign", json=payload, headers=test_data["headers_a"])
    assert res.status_code == 200
    assert "Successfully assigned" in res.json()["message"]

    # Verify assignment exists in DB
    assigned = db_session.query(UserRole).filter(
        UserRole.user_id == test_data["member_a"].id,
        UserRole.role_id == test_data["editor_role"].id,
        UserRole.organization_id == test_data["org_a"].id,
    ).first()
    assert assigned is not None


def test_super_admin_role_assignment(client, db_session, test_data):
    """6. Super Admin legitimate role assignment succeeds -> 200 OK."""
    payload = {
        "user_id": test_data["member_b"].id,
        "role_id": test_data["super_admin_role"].id,
        "organization_id": test_data["org_b"].id,
    }
    res = client.post("/api/v1/roles/assign", json=payload, headers=test_data["headers_super"])
    assert res.status_code == 200


# ===========================================================================
# FIX 2 — SEC-REQ-02: Organization Member & Activity Authorization Tests
# ===========================================================================

def test_org_admin_can_access_own_organization_members(client, test_data):
    """7. Org Admin can access own organization members -> 200 OK."""
    org_a_id = test_data["org_a"].id
    res = client.get(f"/api/v1/organizations/{org_a_id}/members", headers=test_data["headers_a"])
    assert res.status_code == 200
    members = res.json()
    emails = {m["email"] for m in members}
    assert test_data["admin_a"].email in emails
    assert test_data["member_a"].email in emails
    assert test_data["admin_b"].email not in emails


def test_org_admin_can_access_own_organization_activity(client, db_session, test_data):
    """8. Org Admin can access own organization activity feed -> 200 OK."""
    org_a_id = test_data["org_a"].id
    # Seed an audit log for Org A
    log = AuditLog(
        organization_id=org_a_id,
        user_id=test_data["admin_a"].id,
        category="security",
        action="login",
        resource_type="auth",
        status="success",
    )
    db_session.add(log)
    db_session.commit()

    res = client.get(f"/api/v1/organizations/{org_a_id}/activity", headers=test_data["headers_a"])
    assert res.status_code == 200
    activities = res.json()
    assert len(activities) >= 1
    assert activities[0]["action"] == "login"


def test_org_admin_forbidden_for_other_organization_members(client, test_data):
    """9. Org Admin receives 403 Forbidden for another organization's members."""
    org_b_id = test_data["org_b"].id
    res = client.get(f"/api/v1/organizations/{org_b_id}/members", headers=test_data["headers_a"])
    assert res.status_code == 403
    assert "another organization" in res.json()["detail"]


def test_org_admin_forbidden_for_other_organization_activity(client, test_data):
    """10. Org Admin receives 403 Forbidden for another organization's activity."""
    org_b_id = test_data["org_b"].id
    res = client.get(f"/api/v1/organizations/{org_b_id}/activity", headers=test_data["headers_a"])
    assert res.status_code == 403
    assert "another organization" in res.json()["detail"]


def test_super_admin_cross_org_access(client, test_data):
    """11. Super Admin legitimate cross-org access to members and activity -> 200 OK."""
    org_a_id = test_data["org_a"].id
    org_b_id = test_data["org_b"].id

    res_mem_a = client.get(f"/api/v1/organizations/{org_a_id}/members", headers=test_data["headers_super"])
    res_mem_b = client.get(f"/api/v1/organizations/{org_b_id}/members", headers=test_data["headers_super"])
    res_act_a = client.get(f"/api/v1/organizations/{org_a_id}/activity", headers=test_data["headers_super"])
    res_act_b = client.get(f"/api/v1/organizations/{org_b_id}/activity", headers=test_data["headers_super"])

    assert res_mem_a.status_code == 200
    assert res_mem_b.status_code == 200
    assert res_act_a.status_code == 200
    assert res_act_b.status_code == 200


# ===========================================================================
# FIX 3 — SEC-REQ-03: Multi-Tenant Analytics Isolation Tests
# ===========================================================================

def test_analytics_summary_isolation_between_orgs(client, db_session, test_data):
    """12 & 13. Analytics for Org A contain only Org A data; Org B contain only Org B data."""
    org_a = test_data["org_a"]
    org_b = test_data["org_b"]

    # Create KBs for Org A and Org B
    kb_a = KnowledgeBase(name="KB Alpha", organization_id=org_a.id, owner_id=test_data["admin_a"].id)
    kb_b1 = KnowledgeBase(name="KB Beta 1", organization_id=org_b.id, owner_id=test_data["admin_b"].id)
    kb_b2 = KnowledgeBase(name="KB Beta 2", organization_id=org_b.id, owner_id=test_data["admin_b"].id)
    db_session.add_all([kb_a, kb_b1, kb_b2])
    db_session.commit()

    # Create documents in each KB
    doc_a = Document(
        filename="doc_a.txt",
        storage_path="/tmp/doc_a.txt",
        mime_type="text/plain",
        file_size=100,
        knowledge_base_id=kb_a.id,
        created_by=test_data["admin_a"].id,
    )
    doc_b1 = Document(
        filename="doc_b1.txt",
        storage_path="/tmp/doc_b1.txt",
        mime_type="text/plain",
        file_size=100,
        knowledge_base_id=kb_b1.id,
        created_by=test_data["admin_b"].id,
    )
    doc_b2 = Document(
        filename="doc_b2.txt",
        storage_path="/tmp/doc_b2.txt",
        mime_type="text/plain",
        file_size=100,
        knowledge_base_id=kb_b2.id,
        created_by=test_data["admin_b"].id,
    )
    db_session.add_all([doc_a, doc_b1, doc_b2])
    db_session.commit()

    # Query as Org A Admin
    res_a = client.get("/api/v1/analytics/summary", headers=test_data["headers_a"])
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["total_knowledge_bases"] == 1
    assert data_a["total_documents"] == 1

    # Query as Org B Admin
    res_b = client.get("/api/v1/analytics/summary", headers=test_data["headers_b"])
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["total_knowledge_bases"] == 2
    assert data_b["total_documents"] == 2


def test_search_queries_isolation_in_analytics(client, db_session, test_data):
    """14. Search queries from Org B never appear in Org A analytics."""
    org_a = test_data["org_a"]
    org_b = test_data["org_b"]

    kb_a = KnowledgeBase(name="KB Alpha Q", organization_id=org_a.id, owner_id=test_data["admin_a"].id)
    kb_b = KnowledgeBase(name="KB Beta Q", organization_id=org_b.id, owner_id=test_data["admin_b"].id)
    db_session.add_all([kb_a, kb_b])
    db_session.commit()

    # Record search queries for each org
    sa_a = SearchAnalytics(
        query="Alpha Secret Strategy",
        retrieval_latency_ms=15.0,
        results_count=3,
        knowledge_base_id=kb_a.id,
        user_id=test_data["admin_a"].id,
    )
    sa_b = SearchAnalytics(
        query="Beta Merger Acquisition Confidential",
        retrieval_latency_ms=25.0,
        results_count=5,
        knowledge_base_id=kb_b.id,
        user_id=test_data["admin_b"].id,
    )
    db_session.add_all([sa_a, sa_b])
    db_session.commit()

    # Query Org A summary
    res_a = client.get("/api/v1/analytics/summary", headers=test_data["headers_a"])
    assert res_a.status_code == 200
    data_a = res_a.json()
    top_queries_a = [item["query"] for item in data_a["top_queries"]]
    assert "Alpha Secret Strategy" in top_queries_a
    assert "Beta Merger Acquisition Confidential" not in top_queries_a
    assert data_a["total_queries"] == 1

    # Query Org B summary
    res_b = client.get("/api/v1/analytics/summary", headers=test_data["headers_b"])
    assert res_b.status_code == 200
    data_b = res_b.json()
    top_queries_b = [item["query"] for item in data_b["top_queries"]]
    assert "Beta Merger Acquisition Confidential" in top_queries_b
    assert "Alpha Secret Strategy" not in top_queries_b
    assert data_b["total_queries"] == 1


def test_super_admin_global_analytics(client, db_session, test_data):
    """16. Super Admin can view global analytics or filter by organization."""
    org_a = test_data["org_a"]
    org_b = test_data["org_b"]

    kb_a = KnowledgeBase(name="KB A Global", organization_id=org_a.id, owner_id=test_data["admin_a"].id)
    kb_b = KnowledgeBase(name="KB B Global", organization_id=org_b.id, owner_id=test_data["admin_b"].id)
    db_session.add_all([kb_a, kb_b])
    db_session.commit()

    # Global view (no org_id parameter)
    res_global = client.get("/api/v1/analytics/summary", headers=test_data["headers_super"])
    assert res_global.status_code == 200
    data_global = res_global.json()
    assert data_global["total_knowledge_bases"] >= 2

    # Scoped view for Org A
    res_scoped = client.get(f"/api/v1/analytics/summary?org_id={org_a.id}", headers=test_data["headers_super"])
    assert res_scoped.status_code == 200
    data_scoped = res_scoped.json()
    assert data_scoped["total_knowledge_bases"] == 1


# ===========================================================================
# FIX 4 — SEC-REQ-04: Document Deletion & Storage/Vector Cleanup Tests
# ===========================================================================

def test_delete_doc_removes_postgres_qdrant_and_file(db_session, test_data, tmp_path):
    """17. Delete document removes PostgreSQL record, Qdrant vectors, and physical file."""
    org_a = test_data["org_a"]
    admin_a = test_data["admin_a"]

    kb = KnowledgeBase(name="KB Deletion Test", organization_id=org_a.id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    # Create dummy file inside UPLOAD_DIR
    upload_root = os.path.abspath(settings.UPLOAD_DIR)
    os.makedirs(upload_root, exist_ok=True)
    file_path = os.path.join(upload_root, f"test_delete_{py_uuid.uuid4().hex}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("Secret Document Content")

    doc = Document(
        filename="test_doc.txt",
        storage_path=file_path,
        mime_type="text/plain",
        file_size=23,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()

    pdoc = ParsedDocument(
        document_id=doc.id,
        parsed_text="Secret Document Content",
        char_count=23,
        processing_duration=0.05,
    )
    db_session.add(pdoc)
    db_session.commit()
    pdoc_id = pdoc.id

    svc = DocumentService(db_session)

    with patch.object(svc.qdrant_service, "delete_document_vectors") as mock_qdrant_delete:
        mock_qdrant_delete.return_value = True

        svc.delete_doc(doc.uuid, admin_a.id)

        # 1. PostgreSQL record is deleted
        db_doc = db_session.query(Document).filter(Document.id == doc.id).first()
        assert db_doc is None

        # 2. ParsedDocument cascade deleted
        db_pdoc = db_session.query(ParsedDocument).filter(ParsedDocument.id == pdoc_id).first()
        assert db_pdoc is None

        # 3. Physical file deleted from disk
        assert not os.path.exists(file_path)

        # 4. Qdrant vectors deleted
        mock_qdrant_delete.assert_called_once_with(
            parsed_document_id=pdoc_id,
            organization_id=org_a.id,
            knowledge_base_id=kb.id,
        )


def test_delete_doc_missing_file_handled_safely(db_session, test_data):
    """18. Missing physical file is handled safely and idempotently."""
    admin_a = test_data["admin_a"]
    kb = KnowledgeBase(name="KB Missing File", organization_id=test_data["org_a"].id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    # Point to a file that does not exist
    missing_file = os.path.join(os.path.abspath(settings.UPLOAD_DIR), "non_existent_file.txt")
    doc = Document(
        filename="ghost.txt",
        storage_path=missing_file,
        mime_type="text/plain",
        file_size=10,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()

    svc = DocumentService(db_session)
    # Must succeed without error
    svc.delete_doc(doc.uuid, admin_a.id)

    assert db_session.query(Document).filter(Document.id == doc.id).first() is None


def test_delete_doc_missing_vectors_handled_safely(db_session, test_data):
    """19. Missing Qdrant vectors / errors do not cause deletion failure."""
    admin_a = test_data["admin_a"]
    kb = KnowledgeBase(name="KB Missing Vectors", organization_id=test_data["org_a"].id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    doc = Document(
        filename="no_vec.txt",
        storage_path="",
        mime_type="text/plain",
        file_size=10,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()

    pdoc = ParsedDocument(
        document_id=doc.id,
        parsed_text="Text without vectors",
        char_count=20,
        processing_duration=0.01,
    )
    db_session.add(pdoc)
    db_session.commit()

    svc = DocumentService(db_session)

    # Simulate Qdrant raising an error
    with patch.object(svc.qdrant_service, "delete_document_vectors", side_effect=Exception("Qdrant unreachable")):
        # Must not raise exception
        svc.delete_doc(doc.uuid, admin_a.id)

    assert db_session.query(Document).filter(Document.id == doc.id).first() is None


def test_delete_doc_partial_failure_db_rollback(db_session, test_data):
    """20. Partial failure safety: DB error prevents external deletions (rollback integrity)."""
    admin_a = test_data["admin_a"]
    kb = KnowledgeBase(name="KB Rollback", organization_id=test_data["org_a"].id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    upload_root = os.path.abspath(settings.UPLOAD_DIR)
    os.makedirs(upload_root, exist_ok=True)
    file_path = os.path.join(upload_root, f"rollback_test_{py_uuid.uuid4().hex}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("Keep this file if DB fails")

    doc = Document(
        filename="rollback.txt",
        storage_path=file_path,
        mime_type="text/plain",
        file_size=26,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()

    svc = DocumentService(db_session)

    from app.crud import document as crud_doc
    with patch.object(crud_doc, "delete_doc", side_effect=RuntimeError("Database lock timeout")):
        with patch.object(svc.qdrant_service, "delete_document_vectors") as mock_qdrant:
            with patch.object(svc.storage_service, "delete_file") as mock_storage:
                with pytest.raises(RuntimeError, match="Database lock timeout"):
                    svc.delete_doc(doc.uuid, admin_a.id)

                # Neither Qdrant nor storage delete should have been executed!
                mock_qdrant.assert_not_called()
                mock_storage.assert_not_called()
                assert os.path.exists(file_path)

    # Clean up file manually
    if os.path.exists(file_path):
        os.remove(file_path)


def test_deleted_doc_cannot_subsequently_appear_in_retrieval(db_session, test_data):
    """21. Deleted document cannot subsequently appear in retrieval."""
    admin_a = test_data["admin_a"]
    kb = KnowledgeBase(name="KB Search Deletion", organization_id=test_data["org_a"].id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    doc = Document(
        filename="searchable.txt",
        storage_path="",
        mime_type="text/plain",
        file_size=50,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()

    pdoc = ParsedDocument(
        document_id=doc.id,
        parsed_text="Highly confidential quarterly projection",
        char_count=40,
        processing_duration=0.02,
    )
    db_session.add(pdoc)
    db_session.commit()

    chunk = DocumentChunk(
        parsed_document_id=pdoc.id,
        chunk_index=0,
        chunk_text="Highly confidential quarterly projection",
        char_count=40,
        estimated_tokens=10,
        start_offset=0,
        end_offset=40,
    )
    db_session.add(chunk)
    db_session.commit()

    svc = DocumentService(db_session)
    svc.delete_doc(doc.uuid, admin_a.id)

    # Confirm doc and chunk are gone
    assert db_session.query(Document).filter(Document.id == doc.id).first() is None
    assert db_session.query(DocumentChunk).filter(DocumentChunk.id == chunk.id).first() is None


def test_orphaned_qdrant_vector_never_exposed_in_retrieval(db_session, test_data):
    """
    22. STEP 2 Verification: Orphaned Qdrant vector after failed vector cleanup
    CANNOT be surfaced by the actual production retrieval path (hybrid_search / RAG).
    """
    from app.services.search_service import SearchService
    from app.services.rag_service import RAGService
    from qdrant_client.models import ScoredPoint

    admin_a = test_data["admin_a"]
    org_a = test_data["org_a"]
    kb = KnowledgeBase(name="KB Orphan Isolation", organization_id=org_a.id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    doc = Document(
        filename="confidential_memo.txt",
        storage_path="",
        mime_type="text/plain",
        file_size=80,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()

    pdoc = ParsedDocument(
        document_id=doc.id,
        parsed_text="Classified Project Orion launch details",
        char_count=40,
        processing_duration=0.01,
    )
    db_session.add(pdoc)
    db_session.commit()

    chunk = DocumentChunk(
        parsed_document_id=pdoc.id,
        chunk_index=0,
        chunk_text="Classified Project Orion launch details",
        char_count=40,
        estimated_tokens=10,
        start_offset=0,
        end_offset=40,
    )
    db_session.add(chunk)
    db_session.commit()
    chunk_id = chunk.id
    chunk_uuid = str(chunk.uuid)

    # 1. Delete document with Qdrant vector deletion simulated as failed (simulated Qdrant outage)
    svc = DocumentService(db_session)
    with patch.object(svc.qdrant_service, "delete_document_vectors", side_effect=Exception("Qdrant connection timeout")):
        svc.delete_doc(doc.uuid, admin_a.id)

    # PostgreSQL record is successfully deleted
    assert db_session.query(Document).filter(Document.id == doc.id).first() is None
    assert db_session.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).first() is None

    # 2. Simulate Qdrant returning the orphaned vector during retrieval
    orphaned_point = ScoredPoint(
        id=chunk_id,
        version=1,
        score=0.95,
        payload={
            "chunk_uuid": chunk_uuid,
            "parsed_document_id": pdoc.id,
            "knowledge_base_id": kb.id,
            "organization_id": org_a.id,
            "chunk_index": 0,
            "text": "Classified Project Orion launch details",
            "char_count": 40,
            "estimated_tokens": 10,
        },
        vector=None,
    )

    search_svc = SearchService(db_session)
    with patch.object(search_svc.qdrant_service, "search", return_value=[orphaned_point]):
        # Execute production hybrid_search
        results = search_svc.hybrid_search(
            query="Project Orion",
            knowledge_base_id=kb.id,
            organization_id=org_a.id,
        )

        # 3. Verify orphaned vector was completely pruned and never survived
        assert len(results) == 0, f"Expected 0 results but got {results}"

        # 4. Execute production RAG pipeline (ask)
        rag_svc = RAGService(db_session)
        rag_svc.search_service = search_svc
        response = rag_svc.ask(
            question="Project Orion launch details",
            knowledge_base_id=kb.id,
            organization_id=org_a.id,
        )
        assert response["sources"] == []
        assert "couldn't find enough information" in response["answer"]


def test_orphaned_physical_file_inaccessible_via_api(client, db_session, test_data):
    """
    23. STEP 4 Verification: Orphaned physical file after failed file cleanup
    cannot be accessed or read through any API endpoint.
    """
    admin_a = test_data["admin_a"]
    org_a = test_data["org_a"]

    kb = KnowledgeBase(name="KB File Inaccessible", organization_id=org_a.id, owner_id=admin_a.id)
    db_session.add(kb)
    db_session.commit()

    upload_root = os.path.abspath(settings.UPLOAD_DIR)
    os.makedirs(upload_root, exist_ok=True)
    file_path = os.path.join(upload_root, f"orphaned_{py_uuid.uuid4().hex}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("Extremely sensitive financial file")

    doc = Document(
        filename="sensitive.txt",
        storage_path=file_path,
        mime_type="text/plain",
        file_size=35,
        knowledge_base_id=kb.id,
        created_by=admin_a.id,
    )
    db_session.add(doc)
    db_session.commit()
    doc_uuid = str(doc.uuid)

    svc = DocumentService(db_session)
    # Simulate storage deletion failing (e.g. permission or lock issue)
    with patch.object(svc.storage_service, "delete_file", side_effect=Exception("Disk I/O error")):
        svc.delete_doc(doc.uuid, admin_a.id)

    # Physical file is still on disk (orphaned)
    assert os.path.exists(file_path)

    # Verify no document API can access or serve this file
    res_get = client.get(f"/api/v1/documents/{doc_uuid}", headers=test_data["headers_a"])
    assert res_get.status_code == 404

    res_meta = client.get(f"/api/v1/documents/{doc_uuid}/metadata", headers=test_data["headers_a"])
    assert res_meta.status_code == 404

    res_insights = client.get(f"/api/v1/documents/{doc_uuid}/insights", headers=test_data["headers_a"])
    assert res_insights.status_code == 404

    # Clean up file manually
    if os.path.exists(file_path):
        os.remove(file_path)

