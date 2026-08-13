import pytest
import io
import uuid as py_uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.core.security import create_access_token
from app.services.storage_service import StorageService

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

def create_test_user(db_session, email: str, full_name: str):
    from app.models.user import User
    from app.repositories.role_repository import RoleRepository
    import bcrypt
    hashed = bcrypt.hashpw(b"Secure@12345", bcrypt.gensalt())
    user = User(
        email=email,
        hashed_password=hashed.decode(),
        full_name=full_name,
        role="admin",
        organization="Test Org"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    role_repo = RoleRepository(db_session)
    admin_role = role_repo.get_by_name("Super Admin")
    if admin_role:
        role_repo.assign_role_to_user(user.id, admin_role.id)
        db_session.commit()
    return user

def create_test_kb(db_session, owner_id: int, name: str):
    from app.models.knowledge_base import KnowledgeBase
    kb = KnowledgeBase(
        name=name,
        description="Test Collection",
        owner_id=owner_id,
        created_by=owner_id,
        updated_by=owner_id
    )
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)
    return kb

def test_successful_uploads(client, db_session):
    # 1. Setup User & Knowledge Base
    user = create_test_user(db_session, "user1@test.com", "Test User 1")
    kb = create_test_kb(db_session, user.id, "User 1 KB")
    token = create_access_token(user.email)
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Test PDF upload
    pdf_content = b"%PDF-1.4 test pdf content"
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"knowledge_base_uuid": str(kb.uuid)},
        files={"file": ("sample.pdf", pdf_content, "application/pdf")}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "sample.pdf"
    assert data["mime_type"] == "application/pdf"
    assert data["file_size"] == len(pdf_content)
    assert data["status"] == "Queued"
    assert data["sha256_hash"] is not None
    assert data["language"] is None

    # 3. Test DOCX upload
    docx_content = b"docx binary content"
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"knowledge_base_uuid": str(kb.uuid)},
        files={"file": ("sample.docx", docx_content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert response.status_code == 201

    # 4. Test TXT upload
    txt_content = b"plain text content"
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"knowledge_base_uuid": str(kb.uuid)},
        files={"file": ("sample.txt", txt_content, "text/plain")}
    )
    assert response.status_code == 201

    # 5. Test MD upload
    md_content = b"# Markdown Content"
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"knowledge_base_uuid": str(kb.uuid)},
        files={"file": ("sample.md", md_content, "text/markdown")}
    )
    assert response.status_code == 201

def test_invalid_file_type(client, db_session):
    user = create_test_user(db_session, "user1@test.com", "Test User 1")
    kb = create_test_kb(db_session, user.id, "User 1 KB")
    token = create_access_token(user.email)
    headers = {"Authorization": f"Bearer {token}"}
    
    # Try uploading executable file
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"knowledge_base_uuid": str(kb.uuid)},
        files={"file": ("danger.exe", b"binary executable", "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "Unsupported file extension" in response.json()["detail"]

def test_oversized_file(client, db_session):
    user = create_test_user(db_session, "user1@test.com", "Test User 1")
    kb = create_test_kb(db_session, user.id, "User 1 KB")
    token = create_access_token(user.email)
    headers = {"Authorization": f"Bearer {token}"}
    
    # Save original max size and adjust to test-friendly 10 bytes limit
    original_max = StorageService.MAX_FILE_SIZE
    StorageService.MAX_FILE_SIZE = 10
    
    try:
        response = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"knowledge_base_uuid": str(kb.uuid)},
            files={"file": ("sample.txt", b"this string is longer than ten bytes", "text/plain")}
        )
        assert response.status_code == 413
        assert "exceeds maximum upload size" in response.json()["detail"]
    finally:
        StorageService.MAX_FILE_SIZE = original_max

def test_unauthorized_user(client, db_session):
    user = create_test_user(db_session, "user1@test.com", "Test User 1")
    kb = create_test_kb(db_session, user.id, "User 1 KB")
    
    # Request without Authorization headers
    response = client.post(
        "/api/v1/documents/upload",
        data={"knowledge_base_uuid": str(kb.uuid)},
        files={"file": ("sample.txt", b"plain text", "text/plain")}
    )
    assert response.status_code == 401

def test_invalid_knowledge_base(client, db_session):
    user = create_test_user(db_session, "user1@test.com", "Test User 1")
    token = create_access_token(user.email)
    headers = {"Authorization": f"Bearer {token}"}
    
    random_uuid = str(py_uuid.uuid4())
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"knowledge_base_uuid": random_uuid},
        files={"file": ("sample.txt", b"plain text", "text/plain")}
    )
    assert response.status_code == 404
    assert "Knowledge Base not found" in response.json()["detail"]

def test_kb_ownership_validation(client, db_session):
    # User 1 (uploader)
    user1 = create_test_user(db_session, "user1@test.com", "Test User 1")
    token1 = create_access_token(user1.email)
    headers1 = {"Authorization": f"Bearer {token1}"}
    
    # User 2 (owner of target KB)
    user2 = create_test_user(db_session, "user2@test.com", "Test User 2")
    kb2 = create_test_kb(db_session, user2.id, "User 2 KB")
    
    # User 1 tries to upload into User 2's KB
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers1,
        data={"knowledge_base_uuid": str(kb2.uuid)},
        files={"file": ("sample.txt", b"plain text", "text/plain")}
    )
    # Service filters by user ID, hence raising 404 Not Found
    assert response.status_code == 404
    assert "Knowledge Base not found" in response.json()["detail"]
