"""
test_p1_database_optimization.py — Enterprise Database & Query Optimization Test Suite.

Sprint 15.3 Verification Gate:
- Strict SQL Query Count & N+1 query elimination assertions.
- Dashboard single-pass aggregation correctness (empty datasets, multi-tenant isolation, NULLs).
- Conversation message count batching.
- Organization member batching & role lookups.
- Usage trends 7-day range aggregation.
- Unique constraint and index coverage.
- Tenant isolation preservation across all optimized queries.
"""

import datetime
import uuid as py_uuid
from contextlib import contextmanager
from typing import List

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal, engine
from app.models.user import User
from app.models.organization import Organization, OrganizationMember
from app.models.workspace import Workspace
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.models.parsed_document import ParsedDocument
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.audit_log import AuditLog
from app.models.role import Role, UserRole
from app.models.search_analytics import SearchAnalytics
from app.crud.document import get_docs, get_doc_by_uuid
from app.crud.conversation import ConversationRepository
from app.services.conversation_service import ConversationService
from app.services.dashboard_service import DashboardService
from app.services.analytics_service import UsageAnalyticsSubservice
from app.services.organization_service import OrganizationService
from app.repositories.audit_repository import AuditRepository
from app.repositories.invitation_repository import InvitationRepository
from app.models.organization_invitation import OrganizationInvitation


@contextmanager
def capture_queries(connection_or_engine):
    """Context manager to intercept and count all SQL queries executed."""
    queries = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        queries.append({"sql": statement, "params": parameters})

    event.listen(connection_or_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield queries
    finally:
        event.remove(connection_or_engine, "before_cursor_execute", before_cursor_execute)


@pytest.fixture
def db_session():
    """Yields a dedicated test DB session that rolls back after test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_data(db_session: Session):
    """Creates isolated test users, organizations, knowledge bases, and documents."""
    u_suffix = py_uuid.uuid4().hex[:8]
    
    user1 = User(
        email=f"perf_user1_{u_suffix}@example.com",
        hashed_password="fakehashedpassword",
        full_name="Perf User One",
        role="Admin",
        organization="Perf Org A",
        is_active=True,
    )
    user2 = User(
        email=f"perf_user2_{u_suffix}@example.com",
        hashed_password="fakehashedpassword",
        full_name="Perf User Two",
        role="Member",
        organization="Perf Org B",
        is_active=True,
    )
    db_session.add_all([user1, user2])
    db_session.commit()
    db_session.refresh(user1)
    db_session.refresh(user2)

    org1 = Organization(name=f"Perf Org A {u_suffix}", slug=f"perf-org-a-{u_suffix}", is_active=True)
    org2 = Organization(name=f"Perf Org B {u_suffix}", slug=f"perf-org-b-{u_suffix}", is_active=True)
    db_session.add_all([org1, org2])
    db_session.commit()
    db_session.refresh(org1)
    db_session.refresh(org2)

    mem1 = OrganizationMember(organization_id=org1.id, user_id=user1.id)
    mem2 = OrganizationMember(organization_id=org2.id, user_id=user2.id)
    db_session.add_all([mem1, mem2])
    db_session.commit()

    kb1 = KnowledgeBase(
        name=f"KB Alpha {u_suffix}",
        owner_id=user1.id,
        organization_id=org1.id,
        is_active=True,
    )
    kb2 = KnowledgeBase(
        name=f"KB Beta {u_suffix}",
        owner_id=user2.id,
        organization_id=org2.id,
        is_active=True,
    )
    db_session.add_all([kb1, kb2])
    db_session.commit()
    db_session.refresh(kb1)
    db_session.refresh(kb2)

    return {
        "user1": user1,
        "user2": user2,
        "org1": org1,
        "org2": org2,
        "kb1": kb1,
        "kb2": kb2,
    }


# ─── 1. Index & Constraint Declarations Verification ──────────────────────────

def test_p1_model_indexes_and_constraints_present():
    """Verify that all critical model table args and indexes are declared."""
    # Documents indexes
    doc_index_names = {idx.name for idx in Document.__table__.indexes}
    assert "ix_documents_kb_created" in doc_index_names
    assert "ix_documents_kb_sha256" in doc_index_names
    assert Document.__table__.c.knowledge_base_id.index is True

    # KnowledgeBase indexes
    kb_index_names = {idx.name for idx in KnowledgeBase.__table__.indexes}
    assert "ix_kb_org_active_created" in kb_index_names
    assert "ix_kb_owner_active_created" in kb_index_names
    assert KnowledgeBase.__table__.c.owner_id.index is True

    # OrganizationMember unique constraint
    org_member_constraints = {c.name for c in OrganizationMember.__table__.constraints}
    assert "uq_org_members_org_user" in org_member_constraints

    # Message indexes
    msg_index_names = {idx.name for idx in Message.__table__.indexes}
    assert "ix_messages_conv_created" in msg_index_names

    # DocumentChunk index
    from app.models.chunk import DocumentChunk
    assert DocumentChunk.__table__.c.parsed_document_id.index is True


# ─── 2. N+1 Elimination: Document Listing & Eager Loading ─────────────────────

def test_p1_document_listing_no_n_plus_one(db_session: Session, test_data: dict):
    """Verify get_docs fetches 10 documents + parsed_doc + KB in exactly 1 SQL query."""
    user1 = test_data["user1"]
    kb1 = test_data["kb1"]
    owner_id = user1.id
    kb_id = kb1.id

    # Seed 10 documents with parsed documents
    docs = []
    for i in range(10):
        doc = Document(
            knowledge_base_id=kb_id,
            filename=f"doc_{i}.pdf",
            storage_path=f"/tmp/doc_{i}.pdf",
            mime_type="application/pdf",
            file_size=1024 * (i + 1),
            status="Parsed",
            created_by=owner_id,
            updated_by=owner_id,
        )
        db_session.add(doc)
        db_session.flush()

        parsed = ParsedDocument(
            document_id=doc.id,
            parsed_text=f"Text for doc {i}",
            parser_version="PDFParser",
            language_confidence=0.99,
            char_count=50,
            page_count=1,
            processing_duration=0.5,
        )
        db_session.add(parsed)
        docs.append(doc)
    db_session.commit()

    # Clear identity map cache so queries hit the database engine
    db_session.expire_all()

    with capture_queries(engine) as queries:
        result_docs = get_docs(db_session, owner_id=owner_id, kb_id=kb_id, page=1, page_size=20)
        
        # Access relationship attributes to verify no lazy load triggers extra queries
        for d in result_docs:
            _ = d.knowledge_base.name
            _ = d.knowledge_base.uuid
            if d.parsed_document:
                _ = d.parsed_document.page_count
                _ = d.parsed_document.char_count

    # Exactly 1 query must be executed (joinedload in action)
    assert len(result_docs) == 10
    assert len(queries) == 1, f"Expected 1 query but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 3. N+1 Elimination: Conversation Listing Message Count Batching ─────────

def test_p1_conversation_listing_message_count_batching(db_session: Session, test_data: dict):
    """Verify ConversationService.list_conversations uses batch message counting (3 queries total)."""
    user1 = test_data["user1"]
    kb1 = test_data["kb1"]
    org1 = test_data["org1"]
    user_id = user1.id
    kb_id = kb1.id
    org_id = org1.id

    # Seed 10 conversations, each with 3 messages
    for i in range(10):
        conv = Conversation(
            user_id=user_id,
            organization_id=org_id,
            knowledge_base_id=kb_id,
            title=f"Conversation {i}",
            status="ACTIVE",
        )
        db_session.add(conv)
        db_session.flush()

        for m in range(3):
            msg = Message(
                conversation_id=conv.id,
                role=MessageRole.USER if m % 2 == 0 else MessageRole.ASSISTANT,
                content=f"Message {m} for conv {i}",
            )
            db_session.add(msg)
    db_session.commit()
    db_session.expire_all()

    service = ConversationService(db_session)

    with capture_queries(engine) as queries:
        resp = service.list_conversations(user_id=user_id, page=1, page_size=20)

    # 1 count query + 1 list query + 1 batch count query = 3 queries (NOT 1 + 1 + 10 = 12)
    assert resp.total == 10
    assert len(resp.conversations) == 10
    for conv_item in resp.conversations:
        assert conv_item.message_count == 3
    assert len(queries) == 3, f"Expected 3 queries but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 4. N+1 Elimination: Audit Log User Eager Loading ─────────────────────────

def test_p1_audit_log_query_eager_loading(db_session: Session, test_data: dict):
    """Verify AuditRepository.query_logs uses joinedload for user (2 queries total)."""
    user1 = test_data["user1"]
    org1 = test_data["org1"]
    user_id = user1.id
    org_id = org1.id
    repo = AuditRepository(db_session)

    # Seed 10 audit logs
    for i in range(10):
        repo.create(
            action=f"Test Action {i}",
            resource_type="Document",
            category="Document",
            user_id=user_id,
            organization_id=org_id,
        )
    db_session.expire_all()

    with capture_queries(engine) as queries:
        logs, total = repo.query_logs(org_id=org_id, page=1, page_size=20)
        for log in logs:
            if log.user:
                _ = log.user.email
                _ = log.user.full_name

    # 1 count query + 1 joinedload select query = 2 queries (NOT 2 + 10 = 12)
    assert total == 10
    assert len(logs) == 10
    assert len(queries) == 2, f"Expected 2 queries but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 5. N+1 Elimination: Organization Members & Role Batching ────────────────

def test_p1_organization_members_batching(db_session: Session, test_data: dict):
    """Verify OrganizationService.get_organization_members executes in 2 queries."""
    org1 = test_data["org1"]
    org_id = org1.id
    u_suffix = py_uuid.uuid4().hex[:6]

    # Create role
    role = Role(name=f"Analyst_{u_suffix}", is_system_role=False, organization_id=org_id)
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)

    # Seed 5 extra members
    for i in range(5):
        u = User(
            email=f"mem_{i}_{u_suffix}@example.com",
            hashed_password="hash",
            full_name=f"Member {i}",
            role="Member",
            organization=org1.name,
            is_active=True,
        )
        db_session.add(u)
        db_session.flush()

        mem = OrganizationMember(organization_id=org_id, user_id=u.id)
        ur = UserRole(user_id=u.id, role_id=role.id, organization_id=org_id)
        db_session.add_all([mem, ur])
    db_session.commit()
    db_session.expire_all()

    svc = OrganizationService(db_session)

    with capture_queries(engine) as queries:
        members_data = svc.get_organization_members(org_id)

    # 1 query for members + user (joinedload) + 1 query for roles batch = 2 queries (NOT 1 + 6 + 6 = 13)
    assert len(members_data) >= 5
    assert len(queries) == 2, f"Expected 2 queries but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 6. Dashboard Single-Pass Aggregation Correctness ─────────────────────────

def test_p1_dashboard_summary_aggregation_accuracy(db_session: Session, test_data: dict):
    """Verify DashboardService.get_summary accuracy and single-pass aggregation."""
    user1 = test_data["user1"]
    kb1 = test_data["kb1"]
    owner_id = user1.id
    kb_id = kb1.id
    svc = DashboardService(db_session)

    # Empty check
    empty_summary = svc.get_summary(owner_id=owner_id)
    assert empty_summary["knowledge_bases"] == 1
    assert empty_summary["documents"] == 0
    assert empty_summary["storage_used"] == 0
    assert empty_summary["last_upload"] is None
    assert empty_summary["uploaded_docs"] == 0
    assert empty_summary["parsing_docs"] == 0
    assert empty_summary["parsed_docs"] == 0
    assert empty_summary["failed_docs"] == 0

    # Seed mixed status documents
    statuses = ["Uploaded", "Parsing", "Parsed", "Parsed", "Failed"]
    sizes = [1000, 2000, 3000, 4000, 5000]
    for s, sz in zip(statuses, sizes):
        d = Document(
            knowledge_base_id=kb_id,
            filename=f"test_{s}_{sz}.pdf",
            storage_path=f"/path/{s}.pdf",
            mime_type="application/pdf",
            file_size=sz,
            status=s,
            created_by=owner_id,
            updated_by=owner_id,
        )
        db_session.add(d)
    db_session.commit()
    db_session.expire_all()

    with capture_queries(engine) as queries:
        summary = svc.get_summary(owner_id=owner_id)

    assert summary["knowledge_bases"] == 1
    assert summary["documents"] == 5
    assert summary["uploaded_docs"] == 1
    assert summary["parsing_docs"] == 1
    assert summary["parsed_docs"] == 2
    assert summary["failed_docs"] == 1
    assert summary["storage_used"] == 15000
    assert summary["last_upload"] is not None
    assert len(summary["recent_activity"]) == 5

    # 1 kb count + 1 doc aggregation + 1 recent docs with joinedload = 3 queries (NOT 9+)
    assert len(queries) == 3, f"Expected 3 queries but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 7. Usage Analytics 7-Day Grouped Consolidation ───────────────────────────

def test_p1_usage_analytics_aggregation_accuracy(db_session: Session, test_data: dict):
    """Verify UsageAnalyticsSubservice.get_usage_trends executes in 2 queries across 7-day range."""
    user1 = test_data["user1"]
    kb1 = test_data["kb1"]

    # Seed document and search analytics records
    doc = Document(
        knowledge_base_id=kb1.id,
        filename="usage_doc.pdf",
        storage_path="/tmp/usage.pdf",
        mime_type="application/pdf",
        file_size=2048,
        status="Parsed",
        created_by=user1.id,
        updated_by=user1.id,
    )
    db_session.add(doc)
    
    analytics = SearchAnalytics(
        user_id=user1.id,
        knowledge_base_id=kb1.id,
        query="Enterprise Arabic NLP",
        retrieval_latency_ms=45.2,
        results_count=3,
    )
    db_session.add(analytics)
    db_session.commit()
    db_session.expire_all()

    svc = UsageAnalyticsSubservice(db_session)

    with capture_queries(engine) as queries:
        trends = svc.get_usage_trends()

    assert "dailyQuestions" in trends
    assert "storageGrowthMb" in trends
    assert len(trends["dailyQuestions"]) == 7
    assert len(trends["storageGrowthMb"]) == 7

    # 1 doc group query + 1 search group query = 2 queries (NOT 14)
    assert len(queries) == 2, f"Expected 2 queries but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 8. Multi-Tenant Query Isolation Invariant ────────────────────────────────

def test_p1_tenant_isolation_preserved_under_optimization(db_session: Session, test_data: dict):
    """Ensure optimized queries strictly enforce tenant boundaries."""
    user1 = test_data["user1"]
    user2 = test_data["user2"]
    kb1 = test_data["kb1"]
    kb2 = test_data["kb2"]

    doc1 = Document(
        knowledge_base_id=kb1.id,
        filename="org1_doc.pdf",
        storage_path="/tmp/org1.pdf",
        mime_type="application/pdf",
        file_size=1000,
        status="Parsed",
        created_by=user1.id,
        updated_by=user1.id,
    )
    doc2 = Document(
        knowledge_base_id=kb2.id,
        filename="org2_doc.pdf",
        storage_path="/tmp/org2.pdf",
        mime_type="application/pdf",
        file_size=2000,
        status="Parsed",
        created_by=user2.id,
        updated_by=user2.id,
    )
    db_session.add_all([doc1, doc2])
    db_session.commit()
    db_session.expire_all()

    # User 1 must only see KB1 and doc1
    docs_user1 = get_docs(db_session, owner_id=user1.id)
    assert len(docs_user1) == 1
    assert docs_user1[0].filename == "org1_doc.pdf"

    # User 2 must only see KB2 and doc2
    docs_user2 = get_docs(db_session, owner_id=user2.id)
    assert len(docs_user2) == 1
    assert docs_user2[0].filename == "org2_doc.pdf"

    # Dashboard service check
    dash_svc = DashboardService(db_session)
    sum1 = dash_svc.get_summary(owner_id=user1.id)
    sum2 = dash_svc.get_summary(owner_id=user2.id)
    assert sum1["documents"] == 1
    assert sum1["storage_used"] == 1000
    assert sum2["documents"] == 1
    assert sum2["storage_used"] == 2000


# ─── 9. Unique Constraint Enforcement ─────────────────────────────────────────

def test_p1_organization_member_unique_constraint(db_session: Session, test_data: dict):
    """Ensure duplicate membership raises IntegrityError."""
    org1 = test_data["org1"]
    u_suffix = py_uuid.uuid4().hex[:6]

    new_user = User(
        email=f"dup_test_{u_suffix}@example.com",
        hashed_password="hash",
        full_name="Dup Test User",
        role="Member",
        organization=org1.name,
        is_active=True,
    )
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    m1 = OrganizationMember(organization_id=org1.id, user_id=new_user.id)
    db_session.add(m1)
    db_session.commit()

    # Adding second membership for same org + user must fail with IntegrityError
    m2 = OrganizationMember(organization_id=org1.id, user_id=new_user.id)
    db_session.add(m2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ─── 10. Eager Loading: Organization Workspaces (selectinload) ────────────────

def test_p1_organization_workspaces_eager_loading(db_session: Session, test_data: dict):
    """Verify OrganizationRepository.get_user_organizations uses selectinload for workspaces."""
    org1 = test_data["org1"]
    user1 = test_data["user1"]
    user_id = user1.id
    org_id = org1.id

    # Create 3 workspaces for org1
    for i in range(3):
        ws = Workspace(organization_id=org_id, name=f"WS_{i}", is_active=True)
        db_session.add(ws)
    db_session.commit()
    db_session.expire_all()

    from app.repositories.organization_repository import OrganizationRepository
    org_repo = OrganizationRepository(db_session)

    with capture_queries(engine) as queries:
        orgs = org_repo.get_user_organizations(user_id=user_id)
        for o in orgs:
            _ = len(o.workspaces)

    # 1 query for user organizations + 1 selectinload query for workspaces = 2 queries
    assert len(orgs) >= 1
    assert len(queries) == 2, f"Expected 2 queries but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 11. Eager Loading: Invitation Role (joinedload) ──────────────────────────

def test_p1_invitation_role_eager_loading(db_session: Session, test_data: dict):
    """Verify InvitationRepository.get_all_by_org uses joinedload for role."""
    org1 = test_data["org1"]
    user1 = test_data["user1"]
    org_id = org1.id
    u_suffix = py_uuid.uuid4().hex[:6]

    role = Role(name=f"Viewer_{u_suffix}", is_system_role=False, organization_id=org_id)
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)

    inv = OrganizationInvitation(
        organization_id=org_id,
        email=f"invited_{u_suffix}@example.com",
        role_id=role.id,
        invited_by_id=user1.id,
        token_hash=f"hash_{u_suffix}",
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
    )
    db_session.add(inv)
    db_session.commit()
    db_session.expire_all()

    repo = InvitationRepository(db_session)

    with capture_queries(engine) as queries:
        invitations = repo.get_all_by_org(org_id=org_id)
        for i in invitations:
            if i.role:
                _ = i.role.name

    # Exactly 1 query with joinedload
    assert len(invitations) >= 1
    assert len(queries) == 1, f"Expected 1 query but got {len(queries)}: {[q['sql'] for q in queries]}"


# ─── 12. Eager Loading: Document Detail by UUID ───────────────────────────────

def test_p1_get_doc_by_uuid_eager_loading(db_session: Session, test_data: dict):
    """Verify get_doc_by_uuid eager loads parsed_document and knowledge_base."""
    user1 = test_data["user1"]
    kb1 = test_data["kb1"]
    owner_id = user1.id
    kb_id = kb1.id

    doc = Document(
        knowledge_base_id=kb_id,
        filename="single_doc.pdf",
        storage_path="/tmp/single.pdf",
        mime_type="application/pdf",
        file_size=4096,
        status="Parsed",
        created_by=owner_id,
        updated_by=owner_id,
    )
    db_session.add(doc)
    db_session.flush()

    parsed = ParsedDocument(
        document_id=doc.id,
        parsed_text="Single doc text content",
        parser_version="PDFParser",
        language_confidence=0.95,
        char_count=100,
        page_count=2,
        processing_duration=0.8,
    )
    db_session.add(parsed)
    db_session.commit()
    doc_uuid = doc.uuid
    db_session.expire_all()

    with capture_queries(engine) as queries:
        fetched_doc = get_doc_by_uuid(db_session, doc_uuid=doc_uuid, owner_id=owner_id)
        assert fetched_doc is not None
        _ = fetched_doc.knowledge_base.name
        _ = fetched_doc.parsed_document.page_count

    # Exactly 1 query with joinedloads
    assert len(queries) == 1, f"Expected 1 query but got {len(queries)}: {[q['sql'] for q in queries]}"
