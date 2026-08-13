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
from app.repositories.role_repository import RoleRepository
from app.repositories.organization_repository import OrganizationRepository
from app.services.backup_service import BackupService, BackupConsistencyVerifier
from app.services.restore_service import RestoreService
from app.services.disaster_recovery_service import DisasterRecoveryService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("s14_7_validation")


def run_s14_7_validation():
    logger.info("==================================================")
    logger.info("STARTING SPRINT 14.7 BACKUP, DISASTER RECOVERY & HA VALIDATION")
    logger.info("==================================================")

    db = SessionLocal()
    client = TestClient(app)

    try:
        # 1. Setup Admin User & Org
        seed_rbac(db)
        admin_email = f"s14_7_admin_{int(time.time())}@arabiq.ai"
        reg_res = client.post(
            "/api/v1/auth/register",
            json={
                "email": admin_email,
                "password": "Password123!",
                "full_name": "Sprint 14.7 Admin",
                "organization": "ArabIQ Backup Corp",
                "preferred_language": "en"
            }
        )
        assert reg_res.status_code in (200, 201)

        token_res = client.post("/api/v1/auth/token", data={"username": admin_email, "password": "Password123!"})
        token = token_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        admin_user = db.query(User).filter(User.email == admin_email).first()
        org_repo = OrganizationRepository(db)
        orgs = org_repo.get_user_organizations(admin_user.id)
        org = orgs[0]

        role_repo = RoleRepository(db)
        super_admin = role_repo.get_by_name("Super Admin")
        role_repo.assign_role_to_user(admin_user.id, super_admin.id, org.id)

        # 2. Pre-Backup Cross-Component Consistency Check Test
        logger.info("--- Step 1: Testing Pre-Backup Consistency Verification ---")
        consistency = BackupConsistencyVerifier.verify_consistency(db)
        assert consistency["is_consistent"] is True and "document_count" in consistency
        logger.info("✓ Pre-Backup Consistency Verification PASSED")

        # 3. Backup Creation & Manifest Generation Test
        logger.info("--- Step 2: Testing Backup Creation & Manifest Generation ---")
        bk_svc = BackupService(db)
        record = bk_svc.create_backup(backup_type="Full", target="All")
        assert record.status == "verified" and record.checksum_sha256 is not None
        assert record.manifest_path is not None and os.path.exists(record.manifest_path)
        logger.info("✓ Backup Creation & Manifest Generation PASSED")

        # 4. SHA-256 Checksum Integrity Test
        logger.info("--- Step 3: Testing Checksum Integrity Validation ---")
        val = bk_svc.validate_backup_integrity(str(record.uuid))
        assert val["is_valid"] is True and val["status"] == "Verified"
        logger.info("✓ Checksum Integrity Validation PASSED")

        # 5. Component-Level & Dry Run Restore Test
        logger.info("--- Step 4: Testing Component-Level & Dry Run Restore ---")
        restore_svc = RestoreService(db)
        dry_run = restore_svc.dry_run_restore(str(record.uuid), component="PostgreSQL")
        assert dry_run["dry_run"] is True and dry_run["integrity_status"] == "Passed"

        rest_exec = restore_svc.execute_restore(str(record.uuid), component="PostgreSQL")
        assert rest_exec["status"] == "Completed"
        logger.info("✓ Component-Level & Dry Run Restore PASSED")

        # 6. Recovery Readiness Score & HA Matrix Test
        logger.info("--- Step 5: Testing Recovery Readiness Score & HA Matrix ---")
        dr_svc = DisasterRecoveryService(db)
        score = dr_svc.calculate_recovery_readiness_score()
        assert score["overall_dr_readiness_score"] >= 90.0

        ha_matrix = dr_svc.get_ha_readiness_matrix()
        assert len(ha_matrix) >= 4 and ha_matrix[0]["ready"] is True
        logger.info("✓ Recovery Readiness Score & HA Matrix PASSED")

        # 7. Disaster Recovery Runbook Generator Test
        logger.info("--- Step 6: Testing Scenario Runbook Generator ---")
        runbook = dr_svc.generate_scenario_runbook("postgresql_failure")
        assert "procedure" in runbook and len(runbook["procedure"]) >= 3
        logger.info("✓ Scenario Runbook Generator PASSED")

        # 8. REST Backup & DR Endpoints Test
        logger.info("--- Step 7: Testing REST Backup & DR Endpoints ---")
        res_list = client.get("/api/v1/backups", headers=headers)
        assert res_list.status_code == 200 and len(res_list.json()) >= 1

        res_val = client.post("/api/v1/backups/validate", json={"backup_uuid": str(record.uuid)}, headers=headers)
        assert res_val.status_code == 200 and res_val.json()["is_valid"] is True

        res_dry = client.post("/api/v1/backups/restore/dry-run", json={"backup_uuid": str(record.uuid), "target_component": "PostgreSQL"}, headers=headers)
        assert res_dry.status_code == 200 and res_dry.json()["dry_run"] is True

        res_readiness = client.get("/api/v1/disaster-recovery/readiness", headers=headers)
        assert res_readiness.status_code == 200 and "scorecard" in res_readiness.json()

        res_rb = client.get("/api/v1/disaster-recovery/runbook/postgresql_failure", headers=headers)
        assert res_rb.status_code == 200 and "procedure" in res_rb.json()
        logger.info("✓ REST Backup & DR Endpoints PASSED")

        logger.info("==================================================")
        logger.info("✓ ALL SPRINT 14.7 BACKUP, DISASTER RECOVERY & HA TESTS PASSED SUCCESSFULLY")
        logger.info("==================================================")
        return True

    finally:
        db.close()


if __name__ == "__main__":
    run_s14_7_validation()
