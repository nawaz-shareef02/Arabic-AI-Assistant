"""
P2-1 Enterprise Authentication Transport Security Tests.

Comprehensive security attack test matrix:
 1. fake csrf cookie cannot authenticate
 2. missing auth cookie returns 401
 3. missing CSRF returns 403
 4. wrong CSRF returns 403
 5. unexpected Origin returns 403
 6. valid Origin + valid CSRF succeeds
 7. Bearer machine client works without CSRF
 8. Cookie + Bearer → cookie wins and CSRF required
 9. login-CSRF bad Origin rejected
10. invitation token cannot authenticate
11. logout clears auth cookie
12. logout clears CSRF cookie
13. expired JWT rejected
14. tampered JWT rejected
15. login JSON does not contain JWT
16. auth cookie HttpOnly
17. CSRF cookie readable (HttpOnly=False)
18. GET skips CSRF
19. CSRF token cryptographically random (256-bit / 64 hex chars)
20. invitation acceptance sets cookie instead of returning JWT
21. production auth cookie Secure
22. normal logout does not invalidate unrelated sessions
23. logout-all invalidates all refresh sessions
24. fake csrf cookie does not authenticate backend API
25. Authorization header cannot bypass cookie CSRF
"""

import pytest
import datetime
from datetime import timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db
from app.database.base import Base
from app.models.user import User
from app.core.security import create_access_token, get_password_hash
from app.core.config import settings, Settings
from app.core.cookies import generate_csrf_token
from app.models.organization import Organization, OrganizationMember
from app.models.user_session import UserSession

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
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(name="registered_user")
def fixture_registered_user(db_session):
    """Seed an active user in the database."""
    hashed_pw = get_password_hash("Secure@12345")
    user = User(
        email="test_user@example.com",
        hashed_password=hashed_pw,
        full_name="Security Test User",
        organization="SecOrg",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    org = Organization(name="SecOrg", slug="secorg")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)

    member = OrganizationMember(organization_id=org.id, user_id=user.id)
    db_session.add(member)
    db_session.commit()
    return user


# ──────────────────────────────────────────────────────────────────────────────
# 1 & 24. Fake CSRF cookie cannot authenticate backend API
# ──────────────────────────────────────────────────────────────────────────────
def test_fake_csrf_cookie_cannot_authenticate(client, registered_user):
    """Test 1 & 24: Having only a csrf_token cookie without a valid auth_token returns 401."""
    client.cookies.set("csrf_token", "fake_csrf_token_value_12345")
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert "Could not validate credentials" in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 2. Missing auth cookie returns 401
# ──────────────────────────────────────────────────────────────────────────────
def test_missing_auth_cookie_returns_401(client):
    """Test 2: Unauthenticated request with no cookies and no Authorization header returns 401."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# 3. Missing CSRF returns 403 on mutating request
# ──────────────────────────────────────────────────────────────────────────────
def test_missing_csrf_returns_403(client, registered_user):
    """Test 3: Mutating request with auth cookie but missing CSRF token returns 403."""
    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id})
    client.cookies.set("auth_token", token)
    # No csrf_token cookie and no X-CSRF-Token header
    resp = client.post("/api/v1/chat/", json={"question": "hello", "knowledge_base_id": 1})
    assert resp.status_code == 403
    assert "CSRF token missing" in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 4. Wrong CSRF returns 403
# ──────────────────────────────────────────────────────────────────────────────
def test_wrong_csrf_returns_403(client, registered_user):
    """Test 4: Mutating request where csrf_token cookie != X-CSRF-Token header returns 403."""
    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id})
    client.cookies.set("auth_token", token)
    client.cookies.set("csrf_token", "token_in_cookie_abc")

    resp = client.post(
        "/api/v1/chat/",
        json={"question": "hello", "knowledge_base_id": 1},
        headers={"X-CSRF-Token": "mismatched_token_xyz"}
    )
    assert resp.status_code == 403
    assert "CSRF token mismatch" in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 5. Unexpected Origin returns 403
# ──────────────────────────────────────────────────────────────────────────────
def test_unexpected_origin_returns_403(client, registered_user):
    """Test 5: Mutating request from an untrusted origin returns 403."""
    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id})
    csrf = generate_csrf_token()
    client.cookies.set("auth_token", token)
    client.cookies.set("csrf_token", csrf)

    resp = client.post(
        "/api/v1/chat/",
        json={"question": "hello", "knowledge_base_id": 1},
        headers={"X-CSRF-Token": csrf, "Origin": "https://evil-attacker.com"}
    )
    assert resp.status_code == 403
    assert "not authorized" in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 6. Valid Origin + Valid CSRF succeeds
# ──────────────────────────────────────────────────────────────────────────────
def test_valid_origin_and_csrf_succeeds(client, db_session, registered_user):
    """Test 6: Mutating request with authorized Origin and matching CSRF succeeds."""
    from app.models.knowledge_base import KnowledgeBase
    org_id = registered_user.organization_memberships[0].organization_id
    kb = KnowledgeBase(name="SecKB", organization_id=org_id, owner_id=registered_user.id)
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)

    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id, "org_id": org_id})
    csrf = generate_csrf_token()
    client.cookies.set("auth_token", token)
    client.cookies.set("csrf_token", csrf)

    with patch("app.services.rag_service.RAGService.ask") as mock_ask:
        mock_ask.return_value = {"answer": "AI Response", "sources": []}
        resp = client.post(
            "/api/v1/chat/",
            json={"question": "What is AI?", "knowledge_base_id": kb.id},
            headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"}
        )
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# 7. Bearer machine client works without CSRF
# ──────────────────────────────────────────────────────────────────────────────
def test_bearer_machine_client_works_without_csrf(client, db_session, registered_user):
    """Test 7: Machine client using Authorization: Bearer does NOT require CSRF."""
    from app.models.knowledge_base import KnowledgeBase
    org_id = registered_user.organization_memberships[0].organization_id
    kb = KnowledgeBase(name="SecKB", organization_id=org_id, owner_id=registered_user.id)
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)

    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id, "org_id": org_id})
    # Ensure no auth_token cookie
    client.cookies.clear()

    with patch("app.services.rag_service.RAGService.ask") as mock_ask:
        mock_ask.return_value = {"answer": "Machine Response", "sources": []}
        resp = client.post(
            "/api/v1/chat/",
            json={"question": "Machine API request", "knowledge_base_id": kb.id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# 8 & 25. Cookie + Bearer → Cookie wins and CSRF required / cannot bypass CSRF
# ──────────────────────────────────────────────────────────────────────────────
def test_cookie_wins_and_bearer_cannot_bypass_csrf(client, registered_user):
    """Test 8 & 25: If both auth cookie and Bearer header exist, cookie wins and CSRF is strictly required."""
    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id})
    client.cookies.set("auth_token", token)
    # Injected Authorization header attempting to bypass CSRF:
    resp = client.post(
        "/api/v1/chat/",
        json={"question": "Attempt CSRF bypass", "knowledge_base_id": 1},
        headers={"Authorization": f"Bearer {token}"}
    )
    # Must fail with 403 because cookie takes precedence and CSRF is missing
    assert resp.status_code == 403
    assert "CSRF token missing" in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 9. Login-CSRF bad Origin rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_login_csrf_bad_origin_rejected(client):
    """Test 9: Pre-auth login and register endpoints reject unauthorized Origin headers."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
        headers={"Origin": "https://malicious-site.com"}
    )
    assert resp.status_code == 403
    assert "not authorized" in resp.text

    reg_resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "password": "Secure@12345",
            "full_name": "New User",
            "organization": "New Org"
        },
        headers={"Origin": "https://malicious-site.com"}
    )
    assert reg_resp.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# 10. Invitation token cannot authenticate API
# ──────────────────────────────────────────────────────────────────────────────
def test_invitation_token_cannot_authenticate(client):
    """Test 10: Raw invitation tokens cannot be used as Bearer JWT authentication."""
    raw_invitation_token = "inv_tok_1234567890abcdef1234567890abcdef"
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw_invitation_token}"}
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# 11 & 12. Logout clears auth and CSRF cookies
# ──────────────────────────────────────────────────────────────────────────────
def test_logout_clears_cookies(client, registered_user):
    """Test 11 & 12: POST /auth/logout clears auth_token and csrf_token cookies and returns 204."""
    token = create_access_token(registered_user.email)
    csrf = generate_csrf_token()
    client.cookies.set("auth_token", token)
    client.cookies.set("csrf_token", csrf)

    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    # Verify set-cookie response headers contain deletion directives for auth_token and csrf_token
    set_cookies = resp.headers.get_list("set-cookie")
    auth_deleted = any("auth_token" in h and ('""' in h or 'max-age=0' in h.lower() or '1970' in h) for h in set_cookies)
    csrf_deleted = any("csrf_token" in h and ('""' in h or 'max-age=0' in h.lower() or '1970' in h) for h in set_cookies)
    assert auth_deleted, f"Expected auth_token deletion header in {set_cookies}"
    assert csrf_deleted, f"Expected csrf_token deletion header in {set_cookies}"


# ──────────────────────────────────────────────────────────────────────────────
# 13. Expired JWT rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_expired_jwt_rejected(client, registered_user):
    """Test 13: Expired JWT cookie returns 401 Token has expired."""
    expired_token = create_access_token(
        subject=registered_user.email,
        expires_delta=timedelta(seconds=-10)
    )
    client.cookies.set("auth_token", expired_token)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert "Token has expired" in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 14. Tampered JWT rejected
# ──────────────────────────────────────────────────────────────────────────────
def test_tampered_jwt_rejected(client, registered_user):
    """Test 14: Tampered or invalid signature JWT returns 401."""
    valid_token = create_access_token(registered_user.email)
    tampered_token = valid_token[:-4] + "abcd"
    client.cookies.set("auth_token", tampered_token)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# 15. Login JSON does not contain JWT
# ──────────────────────────────────────────────────────────────────────────────
def test_login_json_does_not_contain_jwt(client, registered_user):
    """Test 15: POST /auth/login returns user info but no access_token or token_type in body."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Secure@12345"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" not in data
    assert "token_type" not in data
    assert data["email"] == registered_user.email


# ──────────────────────────────────────────────────────────────────────────────
# 16 & 17. Auth cookie HttpOnly and CSRF cookie readable
# ──────────────────────────────────────────────────────────────────────────────
def test_cookie_httponly_flags(client, registered_user):
    """Test 16 & 17: auth_token cookie has HttpOnly flag; csrf_token does not."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Secure@12345"}
    )
    assert resp.status_code == 200
    set_cookies = resp.headers.get_list("set-cookie")

    auth_cookie_header = next((c for c in set_cookies if "auth_token" in c), "")
    csrf_cookie_header = next((c for c in set_cookies if "csrf_token" in c), "")

    assert "httponly" in auth_cookie_header.lower(), "auth_token must be HttpOnly"
    assert "httponly" not in csrf_cookie_header.lower(), "csrf_token must NOT be HttpOnly (readable by JS)"


# ──────────────────────────────────────────────────────────────────────────────
# 18. GET skips CSRF
# ──────────────────────────────────────────────────────────────────────────────
def test_get_skips_csrf(client, registered_user):
    """Test 18: Safe GET requests succeed with auth_token cookie without CSRF headers."""
    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id})
    client.cookies.set("auth_token", token)
    # No csrf_token cookie or X-CSRF-Token header
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == registered_user.email


# ──────────────────────────────────────────────────────────────────────────────
# 19. CSRF token cryptographically random
# ──────────────────────────────────────────────────────────────────────────────
def test_csrf_token_cryptographically_random():
    """Test 19: CSRF token is 256-bit random hex with unique outputs."""
    tokens = {generate_csrf_token() for _ in range(100)}
    assert len(tokens) == 100
    for tok in tokens:
        assert len(tok) == 64  # 32 bytes hex encoded = 64 characters
        int(tok, 16)  # Valid hex


# ──────────────────────────────────────────────────────────────────────────────
# 20. Invitation acceptance sets cookie instead of returning JWT
# ──────────────────────────────────────────────────────────────────────────────
def test_invitation_acceptance_sets_cookie_instead_of_jwt(client, db_session, registered_user):
    """Test 20: Accepting invitation sets HttpOnly cookie and does not expose JWT in body."""
    from app.services.organization_invitation_service import OrganizationInvitationService
    from app.models.role import Role, UserRole

    org = db_session.query(Organization).first()
    admin_role = Role(name="Organization Admin", description="Admin", is_system_role=True, organization_id=org.id)
    member_role = Role(name="Enterprise Member", description="Member", is_system_role=True, organization_id=org.id)
    db_session.add_all([admin_role, member_role])
    db_session.commit()
    db_session.refresh(admin_role)
    db_session.refresh(member_role)

    ur = UserRole(user_id=registered_user.id, role_id=admin_role.id, organization_id=org.id)
    db_session.add(ur)
    db_session.commit()

    inv_svc = OrganizationInvitationService(db_session)
    inv_data = inv_svc.invite_user(
        org_id=org.id,
        email="newinvitee@example.com",
        role_id=member_role.id,
        invited_by_user=registered_user
    )
    raw_token = inv_data["raw_token"]

    resp = client.post(
        "/api/v1/organizations/invitations/accept",
        json={
            "token": raw_token,
            "full_name": "Invited User",
            "password": "Secure@12345"
        }
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" not in body
    assert "token_type" not in body
    assert "auth_token" in resp.cookies
    assert "csrf_token" in resp.cookies


# ──────────────────────────────────────────────────────────────────────────────
# 21. Production auth cookie Secure validation
# ──────────────────────────────────────────────────────────────────────────────
def test_production_auth_cookie_secure():
    """Test 21: Configuration validator enforces AUTH_COOKIE_SECURE=True in production."""
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECURE must be True"):
        Settings(
            DATABASE_URL="postgresql://user:pass@localhost:5432/db",
            SECRET_KEY="0" * 32,
            OLLAMA_URL="http://localhost:11434",
            ENVIRONMENT="production",
            AUTH_COOKIE_SECURE=False,
        )


# ──────────────────────────────────────────────────────────────────────────────
# 22. Normal logout does not invalidate unrelated sessions
# ──────────────────────────────────────────────────────────────────────────────
def test_normal_logout_does_not_invalidate_unrelated_sessions(client, db_session, registered_user):
    """Test 22: POST /auth/logout does NOT touch UserSession records for other devices."""
    sess = UserSession(
        user_id=registered_user.id,
        family_id="fam_123",
        refresh_token_hash="samplehash123",
        browser="Mobile App",
        client_ip="192.168.1.1",
        expires_at=datetime.datetime.now(datetime.timezone.utc) + timedelta(days=7),
        is_active=True,
    )
    db_session.add(sess)
    db_session.commit()

    token = create_access_token(registered_user.email)
    client.cookies.set("auth_token", token)

    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 204

    # Verify UserSession is still active
    db_session.refresh(sess)
    assert sess.is_active is True


# ──────────────────────────────────────────────────────────────────────────────
# 23. Logout-all invalidates all refresh sessions
# ──────────────────────────────────────────────────────────────────────────────
def test_logout_all_invalidates_all_refresh_sessions(client, db_session, registered_user):
    """Test 23: POST /auth/logout-all invalidates all UserSession records across devices."""
    sess1 = UserSession(
        user_id=registered_user.id,
        family_id="fam_1",
        refresh_token_hash="samplehash1",
        browser="Desktop",
        client_ip="192.168.1.1",
        expires_at=datetime.datetime.now(datetime.timezone.utc) + timedelta(days=7),
        is_active=True,
    )
    sess2 = UserSession(
        user_id=registered_user.id,
        family_id="fam_2",
        refresh_token_hash="samplehash2",
        browser="Phone",
        client_ip="192.168.1.2",
        expires_at=datetime.datetime.now(datetime.timezone.utc) + timedelta(days=7),
        is_active=True,
    )
    db_session.add_all([sess1, sess2])
    db_session.commit()

    token = create_access_token(registered_user.email, additional_claims={"user_id": registered_user.id})
    csrf = generate_csrf_token()
    client.cookies.set("auth_token", token)
    client.cookies.set("csrf_token", csrf)

    logout_all_resp = client.post(
        "/api/v1/auth/logout-all",
        headers={"X-CSRF-Token": csrf}
    )
    assert logout_all_resp.status_code == 200

    db_session.refresh(sess1)
    db_session.refresh(sess2)
    assert sess1.is_active is False
    assert sess2.is_active is False
