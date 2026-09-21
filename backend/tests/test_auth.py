import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.core.security import create_access_token
from datetime import timedelta

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

def test_register_success(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "Secure@12345",
            "full_name": "Test User",
            "organization": "Test Org"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert data["organization"] == "Test Org"
    assert "uuid" in data

def test_register_duplicate_email(client):
    # First registration
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "Secure@12345",
            "full_name": "User One",
            "organization": "Test Org"
        }
    )
    # Second registration
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "Another@12345",
            "full_name": "User Two",
            "organization": "Test Org"
        }
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "A user with this email already exists."

def test_register_password_too_short(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "short@example.com",
            "password": "short",
            "full_name": "Short Pass User",
            "organization": "Test Org"
        }
    )
    assert response.status_code == 422

def test_login_success(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "Secure@12345",
            "full_name": "Login User",
            "organization": "Test Org"
        }
    )
    
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "Secure@12345"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" not in data
    assert data["email"] == "login@example.com"
    assert "auth_token" in response.cookies
    assert "csrf_token" in response.cookies

    # Machine / API client token endpoint
    token_resp = client.post(
        "/api/v1/auth/token",
        data={"username": "login@example.com", "password": "Secure@12345"}
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"

def test_login_wrong_password(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "wrongpass@example.com",
            "password": "Secure@12345",
            "full_name": "User",
            "organization": "Test Org"
        }
    )
    
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrongpass@example.com",
            "password": "Wrong@12345"
        }
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"

def test_login_non_existent_user(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "Secure@12345"
        }
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"

def test_get_me_success(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "me@example.com",
            "password": "Secure@12345",
            "full_name": "Me User",
            "organization": "Test Org"
        }
    )
    
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "me@example.com",
            "password": "Secure@12345"
        }
    )
    token = login_response.cookies.get("auth_token")
    
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me@example.com"
    assert data["full_name"] == "Me User"
    assert data["last_login"] is not None

def test_get_me_unauthorized(client):
    client.cookies.clear()
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401

def test_get_me_invalid_token(client):
    client.cookies.clear()
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalidtokenhere"}
    )
    assert response.status_code == 401

def test_get_me_expired_token(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "expired@example.com",
            "password": "Secure@12345",
            "full_name": "Expired User",
            "organization": "Test Org"
        }
    )
    client.cookies.clear()
    
    expired_token = create_access_token(
        subject="expired@example.com",
        expires_delta=timedelta(seconds=-1)
    )
    
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"
