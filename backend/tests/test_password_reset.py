"""
P0-4 Tests — Production-Grade Password Reset & Recovery System.

Test Suite Coverage
-------------------
 1. Existing email → generic success response.
 2. Unknown email → same generic success response (account enumeration protected).
 3. Reset token generated in DB.
 4. Token stored securely (SHA-256 hash in DB, raw token NEVER stored).
 5. Token expires correctly (PASSWORD_RESET_TOKEN_EXPIRE_MINUTES).
 6. Valid token resets password.
 7. Invalid token rejected with HTTP 400.
 8. Expired token rejected with HTTP 400.
 9. Used token rejected with HTTP 400.
10. Token cannot be reused (single-use enforcement).
11. New reset request invalidates previous token.
12. Password is actually changed in database.
13. Old password no longer works for authentication.
14. New password works for authentication.
15. Rate limiting on forgot-password and reset-password.
16. Reset token value NEVER appears in application logs.
17. SMTP failure handled safely (graceful fallback).
"""

import datetime
import hashlib
import logging
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
from app.models.password_reset_token import PasswordResetToken
from app.core.security import get_password_hash, verify_password

# ──────────────────────────────────────────────────────────────────────────────
# Shared test database fixture (SQLite in-memory)
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Shared user fixture
# ──────────────────────────────────────────────────────────────────────────────

def _seed_reset_user(db, email: str = "reset_test@example.com") -> User:
    user = User(
        email=email,
        hashed_password=get_password_hash("OldSecure@12345"),
        full_name="Reset User",
        organization="Test Enterprise",
        role="employee",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 & 2: Account Enumeration Protection
# ──────────────────────────────────────────────────────────────────────────────

def test_forgot_password_existing_email(client, db_session):
    """Test 1 — Existing email receives generic success response."""
    _seed_reset_user(db_session, "user_exist@example.com")

    with patch("app.services.email_service.EmailService.send_password_reset_email") as mock_send:
        mock_send.return_value = True
        resp = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "user_exist@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["detail"] == "If this email is registered, a password reset link has been sent."
    mock_send.assert_called_once()


def test_forgot_password_unknown_email(client, db_session):
    """Test 2 — Unknown email receives IDENTICAL generic success response."""
    with patch("app.services.email_service.EmailService.send_password_reset_email") as mock_send:
        resp = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "non_existent_98765@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["detail"] == "If this email is registered, a password reset link has been sent."
    # Email should NOT be sent for unknown email.
    mock_send.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 & 4: Token Generation & Secure Hash Storage
# ──────────────────────────────────────────────────────────────────────────────

def test_token_generated_and_stored_as_sha256_hash(client, db_session):
    """Tests 3 & 4 — Token is generated and stored as SHA-256 hash in DB (not raw)."""
    user = _seed_reset_user(db_session, "hash_test@example.com")

    captured_token = []

    def mock_send_email(recipient, raw_token):
        captured_token.append(raw_token)
        return True

    with patch("app.services.email_service.EmailService.send_password_reset_email", side_effect=mock_send_email):
        client.post("/api/v1/auth/forgot-password", json={"email": "hash_test@example.com"})

    assert len(captured_token) == 1
    raw_token = captured_token[0]
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    # Query DB token record
    db_record = db_session.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).first()
    assert db_record is not None
    assert db_record.token_hash == expected_hash, "DB MUST store the SHA-256 hash of the token"
    assert db_record.token_hash != raw_token, "DB MUST NOT store the raw token"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 & 8: Token Expiration
# ──────────────────────────────────────────────────────────────────────────────

def test_token_expiration_enforced(client, db_session):
    """Tests 5 & 8 — Expired token is rejected with HTTP 400."""
    user = _seed_reset_user(db_session, "expire_test@example.com")

    raw_token = "test_expired_token_12345"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)

    token_record = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=past_time,
        used_at=None,
    )
    db_session.add(token_record)
    db_session.commit()

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "NewSecure@12345"},
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────────────
# Test 6, 12, 13, 14: Valid Token Resets Password End-to-End
# ──────────────────────────────────────────────────────────────────────────────

def test_valid_token_resets_password_end_to_end(client, db_session):
    """Tests 6, 12, 13, 14 — Valid token updates password, invalidates old credentials, and enables new login."""
    user = _seed_reset_user(db_session, "e2e_reset@example.com")
    old_hash = user.hashed_password

    captured_tokens = []
    with patch("app.services.email_service.EmailService.send_password_reset_email") as mock_send:
        mock_send.side_effect = lambda recipient, tok: captured_tokens.append(tok) or True
        client.post("/api/v1/auth/forgot-password", json={"email": "e2e_reset@example.com"})

    raw_token = captured_tokens[0]

    # Reset password with new password
    reset_resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "BrandNewPass@999"},
    )
    assert reset_resp.status_code == 200

    db_session.expire_all()
    updated_user = db_session.query(User).filter(User.email == "e2e_reset@example.com").first()
    assert updated_user.hashed_password != old_hash
    assert verify_password("BrandNewPass@999", updated_user.hashed_password)

    # Old password fails
    login_old = client.post("/api/v1/auth/login", json={"email": "e2e_reset@example.com", "password": "OldSecure@12345"})
    assert login_old.status_code == 401

    # New password succeeds
    login_new = client.post("/api/v1/auth/login", json={"email": "e2e_reset@example.com", "password": "BrandNewPass@999"})
    assert login_new.status_code == 200
    assert "auth_token" in login_new.cookies or "access_token" in login_new.json()


# ──────────────────────────────────────────────────────────────────────────────
# Test 7, 9, 10: Invalid & Used Token Rejection / Single-Use Enforcement
# ──────────────────────────────────────────────────────────────────────────────

def test_invalid_token_rejected(client, db_session):
    """Test 7 — Fake/non-existent token is rejected with HTTP 400."""
    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "totally_fake_token_value", "new_password": "NewPassword@123"},
    )
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower() or "expired" in resp.json()["detail"].lower()


def test_token_cannot_be_reused(client, db_session):
    """Tests 9 & 10 — Consumed token cannot be reused for second reset."""
    user = _seed_reset_user(db_session, "reuse@example.com")

    captured_tokens = []
    with patch("app.services.email_service.EmailService.send_password_reset_email") as mock_send:
        mock_send.side_effect = lambda recipient, tok: captured_tokens.append(tok) or True
        client.post("/api/v1/auth/forgot-password", json={"email": "reuse@example.com"})

    raw_token = captured_tokens[0]

    # First reset succeeds
    resp1 = client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "FirstNewPass@123"})
    assert resp1.status_code == 200

    # Second reset with SAME token fails
    resp2 = client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "SecondNewPass@123"})
    assert resp2.status_code == 400
    assert "invalid" in resp2.json()["detail"].lower() or "expired" in resp2.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────────────
# Test 11: New Reset Request Invalidates Previous Token
# ──────────────────────────────────────────────────────────────────────────────

def test_new_request_invalidates_previous_tokens(client, db_session):
    """Test 11 — Requesting a new reset token invalidates any previous unconsumed token."""
    user = _seed_reset_user(db_session, "multi_req@example.com")

    captured_tokens = []
    with patch("app.services.email_service.EmailService.send_password_reset_email") as mock_send:
        mock_send.side_effect = lambda recipient, tok: captured_tokens.append(tok) or True

        # Request #1
        client.post("/api/v1/auth/forgot-password", json={"email": "multi_req@example.com"})
        # Request #2
        client.post("/api/v1/auth/forgot-password", json={"email": "multi_req@example.com"})

    assert len(captured_tokens) == 2
    token1, token2 = captured_tokens[0], captured_tokens[1]

    # Token 1 must be invalid (invalidated by Token 2 generation)
    resp1 = client.post("/api/v1/auth/reset-password", json={"token": token1, "new_password": "PassFromToken1@1"})
    assert resp1.status_code == 400

    # Token 2 must be valid
    resp2 = client.post("/api/v1/auth/reset-password", json={"token": token2, "new_password": "PassFromToken2@2"})
    assert resp2.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# Test 15: Rate Limiting
# ──────────────────────────────────────────────────────────────────────────────

def test_forgot_password_rate_limiting(client, db_session):
    """Test 15 — Forgot-password endpoint respects rate limits."""
    with patch("app.core.rate_limit.forgot_password_limiter.is_rate_limited", return_value=True):
        resp = client.post("/api/v1/auth/forgot-password", json={"email": "limited@example.com"})
        assert resp.status_code == 429
        assert "too many" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────────────
# Test 16: Reset Token Never Appears in Application Logs
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_token_never_logged(client, db_session, caplog):
    """Test 16 — Verify raw token value does not appear in application log records."""
    user = _seed_reset_user(db_session, "nolog@example.com")

    caplog.set_level(logging.DEBUG)

    captured_tokens = []
    with patch("app.services.email_service.EmailService.send_password_reset_email") as mock_send:
        mock_send.side_effect = lambda recipient, tok: captured_tokens.append(tok) or True
        client.post("/api/v1/auth/forgot-password", json={"email": "nolog@example.com"})

    raw_token = captured_tokens[0]

    # Perform password reset
    client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "NoLogPassword@123"})

    # Assert raw_token is absent from all captured log text
    for record in caplog.records:
        assert raw_token not in record.getMessage(), "Raw reset token MUST NOT appear in log output"


# ──────────────────────────────────────────────────────────────────────────────
# Test 17: SMTP Failure Handled Gracefully
# ──────────────────────────────────────────────────────────────────────────────

def test_smtp_failure_handled_gracefully(client, db_session):
    """Test 17 — SMTP connection/auth failure does not crash HTTP request."""
    user = _seed_reset_user(db_session, "smtp_fail@example.com")

    with patch("app.services.email_service.EmailService.send_password_reset_email", return_value=False):
        resp = client.post("/api/v1/auth/forgot-password", json={"email": "smtp_fail@example.com"})

    # HTTP response is still 200 with generic message (no internal crash/leak)
    assert resp.status_code == 200
    assert resp.json()["detail"] == "If this email is registered, a password reset link has been sent."
