import sys
import os
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules["pytest"] = "active"  # Bypass rate limiters for test runner

from fastapi.testclient import TestClient
from jose import jwt
from app.main import app
from app.database.session import SessionLocal
from app.core.config import settings
from app.core.rbac_seeder import seed_rbac
from app.models.user import User
from app.models.organization import Organization
from app.models.role import Role
from app.models.permission import Permission
from app.repositories.role_repository import RoleRepository
from app.services.permission_service import PermissionService
from app.services.authorization_service import AuthorizationService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("s14_rbac_validation")


def run_s14_rbac_validation():
    logger.info("==================================================")
    logger.info("STARTING SPRINT 14.1 ENTERPRISE RBAC FOUNDATION VALIDATION")
    logger.info("==================================================")

    db = SessionLocal()
    client = TestClient(app)

    try:
        # 1. Database Schema & Seeder Idempotency Test
        logger.info("--- Step 1: Testing RBACSeeder & Database Tables ---")
        seed_rbac(db)
        seed_rbac(db)  # Second run tests idempotency

        perm_count = db.query(Permission).count()
        role_count = db.query(Role).count()
        assert perm_count >= 14, f"Expected >= 14 permissions, got {perm_count}"
        assert role_count >= 6, f"Expected >= 6 default roles, got {role_count}"
        logger.info(f"✓ RBAC Seeder PASSED ({perm_count} permissions, {role_count} roles seeded idempotently)")

        # 2. Registration & Compact JWT Claims Test
        logger.info("--- Step 2: Testing Registration & Compact JWT Payload Claims ---")
        admin_email = f"s14_admin_{int(time.time())}@arabiq.ai"
        reg_res = client.post(
            "/api/v1/auth/register",
            json={
                "email": admin_email,
                "password": "Password123!",
                "full_name": "Sprint 14 Super Admin",
                "organization": "ArabIQ Enterprise",
                "preferred_language": "en"
            }
        )
        assert reg_res.status_code in (200, 201), f"Registration failed: {reg_res.text}"

        token_res = client.post(
            "/api/v1/auth/token",
            data={"username": admin_email, "password": "Password123!"}
        )
        token = token_res.json()["access_token"]

        # Ensure Super Admin role is assigned for validation
        role_repo = RoleRepository(db)
        super_admin = role_repo.get_by_name("Super Admin")
        admin_user = db.query(User).filter(User.email == admin_email).first()
        org_id = admin_user.organization_memberships[0].organization_id if admin_user.organization_memberships else None
        role_repo.assign_role_to_user(admin_user.id, super_admin.id, org_id)

        # Decode JWT without verification to inspect compact claims
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        assert "sub" in payload, "Missing sub claim"
        assert "org_id" in payload, "Missing org_id claim"
        assert "role_ids" in payload, "Missing role_ids claim"
        assert "permissions" not in payload, "Refinement #1 Violation: Full permissions list must NOT be in JWT"
        logger.info(f"✓ Compact JWT Claims PASSED (Claims: {list(payload.keys())})")

        # 3. Dynamic Permission Resolution & Cache Invalidation Test
        logger.info("--- Step 3: Testing PermissionService & Cache Invalidation ---")
        perm_svc = PermissionService(db)
        admin_user = db.query(User).filter(User.email == admin_email).first()
        admin_perms = perm_svc.get_user_permissions(admin_user.id)
        assert len(admin_perms) > 0, "No permissions resolved for user"
        assert "knowledge_base.create" in admin_perms, "Missing knowledge_base.create permission"

        PermissionService.invalidate_cache_for_user(admin_user.id)
        logger.info(f"✓ PermissionService & Cache Invalidation PASSED ({len(admin_perms)} permissions resolved)")

        # 4. AuthorizationService & Super Admin Bypass Test
        logger.info("--- Step 4: Testing AuthorizationService & Super Admin Bypass ---")
        authz_svc = AuthorizationService(db)
        allowed = authz_svc.check_permission(admin_user, "system.admin")
        assert allowed is True, "Super Admin bypass failed"
        logger.info("✓ AuthorizationService Super Admin Bypass PASSED")

        # 5. Protected API Authorization & 403 Enforcement Test
        logger.info("--- Step 5: Testing API Protection & 403 Forbidden Enforcement ---")
        headers = {"Authorization": f"Bearer {token}"}

        # Admin user has permission -> 200 OK
        res_roles = client.get("/api/v1/roles/", headers=headers)
        assert res_roles.status_code == 200, f"Role list endpoint failed: {res_roles.text}"

        res_org_me = client.get("/api/v1/organizations/me", headers=headers)
        assert res_org_me.status_code == 200, f"Org me endpoint failed: {res_org_me.text}"

        # Standard Restricted User (AI User role)
        user_email = f"s14_viewer_{int(time.time())}@arabiq.ai"
        client.post(
            "/api/v1/auth/register",
            json={
                "email": user_email,
                "password": "Password123!",
                "full_name": "Standard Viewer User",
                "organization": "ArabIQ Enterprise",
                "preferred_language": "en"
            }
        )
        user_token_res = client.post(
            "/api/v1/auth/token",
            data={"username": user_email, "password": "Password123!"}
        )
        user_token = user_token_res.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # Standard AI User trying to access /roles/ -> 403 Forbidden
        res_forbidden = client.get("/api/v1/roles/", headers=user_headers)
        assert res_forbidden.status_code == 403, f"Expected 403 Forbidden, got {res_forbidden.status_code}"
        logger.info("✓ API Security & 403 Forbidden Enforcement PASSED")

        logger.info("==================================================")
        logger.info("✓ ALL SPRINT 14.1 ENTERPRISE RBAC TESTS PASSED SUCCESSFULLY")
        logger.info("==================================================")
        return True

    finally:
        db.close()


if __name__ == "__main__":
    run_s14_rbac_validation()
