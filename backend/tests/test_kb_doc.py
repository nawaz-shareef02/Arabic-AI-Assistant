import pytest
import uuid as py_uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.core.security import create_access_token
from app.schemas.document import DocumentStatus

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
    from app.core.rbac_seeder import seed_rbac
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

@pytest.fixture(name="user_tokens")
def fixture_user_tokens(client):
    # Register and login two separate users for multi-user verification
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "user1@example.com",
            "password": "Secure@12345",
            "full_name": "User One",
            "organization": "Org One"
        }
    )
    r1 = client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "Secure@12345"}
    )
    t1 = r1.json()["access_token"]

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "user2@example.com",
            "password": "Secure@12345",
            "full_name": "User Two",
            "organization": "Org Two"
        }
    )
    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": "user2@example.com", "password": "Secure@12345"}
    )
    t2 = r2.json()["access_token"]

    return t1, t2

def test_kb_crud_flow(client, user_tokens):
    t1, t2 = user_tokens
    headers1 = {"Authorization": f"Bearer {t1}"}
    headers2 = {"Authorization": f"Bearer {t2}"}

    # 1. Create KB for User 1
    res = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Finance KB", "description": "Financial reports"},
        headers=headers1
    )
    assert res.status_code == 201
    kb1 = res.json()
    assert kb1["name"] == "Finance KB"
    assert kb1["is_active"] is True
    kb1_uuid = kb1["uuid"]

    # 2. Get KB details
    res = client.get(f"/api/v1/knowledge-bases/{kb1_uuid}", headers=headers1)
    assert res.status_code == 200
    assert res.json()["name"] == "Finance KB"

    # 3. Prevent User 2 from getting User 1's KB
    res = client.get(f"/api/v1/knowledge-bases/{kb1_uuid}", headers=headers2)
    assert res.status_code == 404

    # 4. Update KB
    res = client.patch(
        f"/api/v1/knowledge-bases/{kb1_uuid}",
        json={"name": "Updated Finance", "description": "New description"},
        headers=headers1
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Finance"

    # 5. Prevent User 2 from updating User 1's KB
    res = client.patch(
        f"/api/v1/knowledge-bases/{kb1_uuid}",
        json={"name": "Hack"},
        headers=headers2
    )
    assert res.status_code == 404

    # 6. Soft Delete KB
    res = client.delete(f"/api/v1/knowledge-bases/{kb1_uuid}", headers=headers1)
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    # 7. Verification: Get KB returns 404 after soft delete
    res = client.get(f"/api/v1/knowledge-bases/{kb1_uuid}", headers=headers1)
    assert res.status_code == 404

def test_kb_list_filters(client, user_tokens):
    t1, _ = user_tokens
    headers = {"Authorization": f"Bearer {t1}"}

    # Create 3 KBs
    client.post("/api/v1/knowledge-bases", json={"name": "HR Policy", "description": "Personnel files"}, headers=headers)
    client.post("/api/v1/knowledge-bases", json={"name": "Finance Budget", "description": "Annual sheets"}, headers=headers)
    client.post("/api/v1/knowledge-bases", json={"name": "IT Setup", "description": "Guides and logs"}, headers=headers)

    # Search filter
    res = client.get("/api/v1/knowledge-bases?search=finance", headers=headers)
    assert res.status_code == 200
    kbs = res.json()
    assert len(kbs) == 1
    assert kbs[0]["name"] == "Finance Budget"

    # Sorting asc by name
    res = client.get("/api/v1/knowledge-bases?sort_by=name&sort_order=asc", headers=headers)
    kbs = res.json()
    assert len(kbs) == 3
    assert kbs[0]["name"] == "Finance Budget"
    assert kbs[1]["name"] == "HR Policy"
    assert kbs[2]["name"] == "IT Setup"

    # Pagination page 2, page_size 2
    res = client.get("/api/v1/knowledge-bases?sort_by=name&sort_order=asc&page=2&page_size=2", headers=headers)
    kbs = res.json()
    assert len(kbs) == 1
    assert kbs[0]["name"] == "IT Setup"

def test_document_crud_flow(client, user_tokens):
    t1, t2 = user_tokens
    headers1 = {"Authorization": f"Bearer {t1}"}
    headers2 = {"Authorization": f"Bearer {t2}"}

    # Create KB for User 1 and User 2
    kb1_res = client.post("/api/v1/knowledge-bases", json={"name": "KB1"}, headers=headers1).json()
    kb2_res = client.post("/api/v1/knowledge-bases", json={"name": "KB2"}, headers=headers2).json()
    kb1_uuid = kb1_res["uuid"]
    kb2_uuid = kb2_res["uuid"]

    # 1. Create Document under KB1 (User 1)
    res = client.post(
        "/api/v1/documents",
        json={
            "filename": "tax.pdf",
            "storage_path": "s3://bucket/tax.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
            "knowledge_base_uuid": kb1_uuid
        },
        headers=headers1
    )
    assert res.status_code == 201
    doc = res.json()
    assert doc["filename"] == "tax.pdf"
    assert doc["status"] == DocumentStatus.QUEUED
    doc_uuid = doc["uuid"]

    # 2. Prevent creating document under another user's KB
    res = client.post(
        "/api/v1/documents",
        json={
            "filename": "hack.pdf",
            "storage_path": "s3://bucket/hack.pdf",
            "mime_type": "application/pdf",
            "file_size": 1024,
            "knowledge_base_uuid": kb2_uuid
        },
        headers=headers1
    )
    assert res.status_code == 404

    # 3. Retrieve Document
    res = client.get(f"/api/v1/documents/{doc_uuid}", headers=headers1)
    assert res.status_code == 200
    assert res.json()["filename"] == "tax.pdf"

    # 4. Prevent User 2 from retrieving User 1's document
    res = client.get(f"/api/v1/documents/{doc_uuid}", headers=headers2)
    assert res.status_code == 404

    # 5. Rename Document
    res = client.patch(f"/api/v1/documents/{doc_uuid}", json={"filename": "tax_updated.pdf"}, headers=headers1)
    assert res.status_code == 200
    assert res.json()["filename"] == "tax_updated.pdf"

    # 6. Move Document to another KB of the same user
    kb1b_res = client.post("/api/v1/knowledge-bases", json={"name": "KB1B"}, headers=headers1).json()
    kb1b_uuid = kb1b_res["uuid"]

    res = client.patch(f"/api/v1/documents/{doc_uuid}", json={"knowledge_base_uuid": kb1b_uuid}, headers=headers1)
    assert res.status_code == 200
    assert res.json()["knowledge_base_uuid"] == kb1b_uuid

    # 7. Prevent moving document to another user's KB
    res = client.patch(f"/api/v1/documents/{doc_uuid}", json={"knowledge_base_uuid": kb2_uuid}, headers=headers1)
    assert res.status_code == 404

    # 8. Delete Document
    res = client.delete(f"/api/v1/documents/{doc_uuid}", headers=headers1)
    assert res.status_code == 204

    # 9. Verify deletion
    res = client.get(f"/api/v1/documents/{doc_uuid}", headers=headers1)
    assert res.status_code == 404

def test_document_list_and_dashboard_summary(client, user_tokens):
    t1, _ = user_tokens
    headers = {"Authorization": f"Bearer {t1}"}

    # Create KB
    kb_res = client.post("/api/v1/knowledge-bases", json={"name": "Reports"}, headers=headers).json()
    kb_uuid = kb_res["uuid"]

    # Create 2 documents
    client.post(
        "/api/v1/documents",
        json={
            "filename": "quarter1.pdf",
            "storage_path": "s3://bucket/q1.pdf",
            "mime_type": "application/pdf",
            "file_size": 1000,
            "knowledge_base_uuid": kb_uuid
        },
        headers=headers
    )
    client.post(
        "/api/v1/documents",
        json={
            "filename": "annual_summary.pdf",
            "storage_path": "s3://bucket/annual.pdf",
            "mime_type": "application/pdf",
            "file_size": 5000,
            "knowledge_base_uuid": kb_uuid
        },
        headers=headers
    )

    # Search documents
    res = client.get("/api/v1/documents?search=annual", headers=headers)
    assert res.status_code == 200
    docs = res.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "annual_summary.pdf"

    # Dashboard summary verification
    res = client.get("/api/v1/dashboard/summary", headers=headers)
    assert res.status_code == 200
    summary = res.json()
    assert summary["knowledge_bases"] == 1
    assert summary["documents"] == 2
    assert summary["storage_used"] == 6000
    assert summary["storage_used_mb"] == round(6000 / (1024 * 1024), 2)
    assert summary["last_upload"] is not None
    assert len(summary["recent_activity"]) == 2
