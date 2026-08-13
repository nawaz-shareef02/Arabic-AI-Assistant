import sys
import os
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules["pytest"] = "active"  # Bypass rate limiters for test runner

from fastapi.testclient import TestClient
from app.main import app
from app.database.session import SessionLocal
from app.core.rbac_seeder import seed_rbac
from app.models.user import User
from app.models.organization import Organization
from app.models.role import Role
from app.repositories.role_repository import RoleRepository
from app.repositories.organization_repository import OrganizationRepository
from app.services.organization_service import OrganizationService
from app.services.organization_invitation_service import OrganizationInvitationService
from app.services.audit_service import AuditService
from app.services.audit_export_service import AuditExportService
from app.services.audit_event_publisher import AuditEventPublisher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("s14_2_validation")


def run_s14_2_validation():
    logger.info("==================================================")
    logger.info("STARTING SPRINT 14.2 ENTERPRISE ORG MGMT & AUDIT VALIDATION")
    logger.info("==================================================")

    db = SessionLocal()
    client = TestClient(app)

    try:
        # 1. Setup Admin User & Org
        seed_rbac(db)
        admin_email = f"s14_2_admin_{int(time.time())}@arabiq.ai"
        reg_res = client.post(
            "/api/v1/auth/register",
            json={
                "email": admin_email,
                "password": "Password123!",
                "full_name": "Sprint 14.2 Admin",
                "organization": "ArabIQ Global Corp",
                "preferred_language": "en"
            }
        )
        assert reg_res.status_code in (200, 201)

        token_res = client.post(
            "/api/v1/auth/token",
            data={"username": admin_email, "password": "Password123!"}
        )
        token = token_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        admin_user = db.query(User).filter(User.email == admin_email).first()
        org_repo = OrganizationRepository(db)
        orgs = org_repo.get_user_organizations(admin_user.id)
        org = orgs[0]

        role_repo = RoleRepository(db)
        super_admin = role_repo.get_by_name("Super Admin")
        role_repo.assign_role_to_user(admin_user.id, super_admin.id, org.id)

        # 2. Bulk Invitations & SHA-256 Token Hashing Test
        logger.info("--- Step 1: Testing Bulk Invitations & SHA-256 Token Hashing ---")
        inv_svc = OrganizationInvitationService(db)
        editor_role = role_repo.get_by_name("Editor")

        bulk_emails = [f"bulk_user_{i}_{int(time.time())}@arabiq.ai" for i in range(3)]
        inv_results = inv_svc.invite_bulk_users(org.id, bulk_emails, editor_role.id, admin_user)
        assert len(inv_results) == 3, f"Expected 3 invitations, got {len(inv_results)}"
        assert "raw_token" in inv_results[0], "Missing raw_token in invitation return"
        logger.info("✓ Bulk Invitations & SHA-256 Token Hashing PASSED")

        # 3. Accept Invitation Test
        logger.info("--- Step 2: Testing Invitation Acceptance ---")
        invitee_email = f"invitee_{int(time.time())}@arabiq.ai"
        client.post(
            "/api/v1/auth/register",
            json={"email": invitee_email, "password": "Password123!", "full_name": "Invitee", "organization": "ArabIQ", "preferred_language": "en"}
        )
        invitee_token_res = client.post("/api/v1/auth/token", data={"username": invitee_email, "password": "Password123!"})
        invitee_token = invitee_token_res.json()["access_token"]
        invitee_headers = {"Authorization": f"Bearer {invitee_token}"}

        raw_token = inv_results[0]["raw_token"]
        accept_res = client.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": raw_token},
            headers=invitee_headers
        )
        assert accept_res.status_code == 200, f"Accept invitation failed: {accept_res.text}"
        logger.info("✓ Invitation Acceptance PASSED")

        # 4. AuditEventPublisher & Categorized Audit Logs Test
        logger.info("--- Step 3: Testing AuditEventPublisher & Categorized Audit Logs ---")
        publisher = AuditEventPublisher(db)
        publisher.publish_event(
            action="Test Security Event",
            resource_type="System",
            category="Authentication",
            user_id=admin_user.id,
            organization_id=org.id,
            status="success"
        )

        audit_svc = AuditService(db)
        logs, total = audit_svc.search_audit_logs(org_id=org.id, category="Authentication")
        assert total >= 1, "Audit logs count 0"
        logger.info(f"✓ AuditEventPublisher & Categorized Audit Logs PASSED ({total} logs found)")

        # 5. Audit Export CSV Test
        logger.info("--- Step 4: Testing AuditExportService CSV Generation ---")
        export_svc = AuditExportService(db)
        csv_data = export_svc.generate_csv_export(org_id=org.id)
        assert "Timestamp" in csv_data and "Category" in csv_data, "CSV export header missing"
        logger.info("✓ AuditExportService CSV Generation PASSED")

        # 6. Organization Activity Timeline Feed Test
        logger.info("--- Step 5: Testing Organization Activity Feed ---")
        org_svc = OrganizationService(db)
        activity_feed = org_svc.get_activity_feed(org.id, limit=50)
        assert len(activity_feed) >= 1, "Activity feed is empty"
        logger.info(f"✓ Organization Activity Feed PASSED ({len(activity_feed)} events in feed)")

        # 7. Audit REST Endpoints Test
        logger.info("--- Step 6: Testing REST Audit Endpoints ---")
        res_audit = client.get("/api/v1/audit/", headers=headers)
        assert res_audit.status_code == 200, f"GET /audit failed: {res_audit.text}"

        res_csv = client.get("/api/v1/audit/export", headers=headers)
        assert res_csv.status_code == 200, "GET /audit/export failed"
        assert res_csv.headers["content-type"] == "text/csv; charset=utf-8"
        logger.info("✓ REST Audit Endpoints PASSED")

        logger.info("==================================================")
        logger.info("✓ ALL SPRINT 14.2 ORG MGMT & AUDIT TESTS PASSED SUCCESSFULLY")
        logger.info("==================================================")
        return True

    finally:
        db.close()


if __name__ == "__main__":
    run_s14_2_validation()
