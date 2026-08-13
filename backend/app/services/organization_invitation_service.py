"""
OrganizationInvitationService — Refinements #2, #3 & #11:
Single & Bulk Onboarding, SHA-256 Token Hashing, and Notification Dispatch.
"""

import uuid
import hashlib
import datetime
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.repositories.invitation_repository import InvitationRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.organization_repository import OrganizationRepository
from app.models.user import User
from app.services.notification_service import NotificationService
from app.services.audit_event_publisher import AuditEventPublisher

logger = logging.getLogger("app.services.organization_invitation_service")


class OrganizationInvitationService:
    def __init__(self, db: Session):
        self.db = db
        self.inv_repo = InvitationRepository(db)
        self.role_repo = RoleRepository(db)
        self.org_repo = OrganizationRepository(db)
        self.notification_service = NotificationService()
        self.publisher = AuditEventPublisher(db)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Refinement #3: Computes SHA-256 hash of raw invitation token."""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def invite_user(
        self,
        org_id: int,
        email: str,
        role_id: int,
        invited_by_user: User,
        base_url: str = "http://localhost:3000",
    ) -> Dict[str, Any]:
        role = self.role_repo.get_all()
        target_role = self.db.query(self.role_repo.db.models.Role if False else type(role[0]) if role else object).filter_by(id=role_id).first() if False else self.db.query(self.inv_repo.db.models.Role if hasattr(self.inv_repo.db, 'models') else object).filter_by(id=role_id).first() if False else self.role_repo.get_all(org_id)
        role_obj = next((r for r in target_role if r.id == role_id), None)
        if not role_obj:
            raise HTTPException(status_code=400, detail="Invalid role ID specified.")

        org = self.org_repo.get_by_id(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        # Generate secure raw token & compute SHA-256 hash for DB storage
        raw_token = str(uuid.uuid4())
        token_hash = self.hash_token(raw_token)
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)

        inv = self.inv_repo.create(
            org_id=org_id,
            email=email.lower().strip(),
            role_id=role_id,
            token_hash=token_hash,
            invited_by_id=invited_by_user.id,
            expires_at=expires_at,
        )

        invitation_link = f"{base_url}/accept-invitation?token={raw_token}"
        self.notification_service.send_organization_invitation(
            to_email=email,
            org_name=org.name,
            invitation_link=invitation_link,
            role_name=role_obj.name,
        )

        self.publisher.publish_event(
            action="Invitation Sent",
            resource_type="OrganizationInvitation",
            category="Organization",
            user_id=invited_by_user.id,
            organization_id=org_id,
            resource_id=str(inv.uuid),
            metadata_json={"email": email, "role": role_obj.name},
        )

        return {
            "uuid": str(inv.uuid),
            "email": inv.email,
            "status": inv.status,
            "expires_at": inv.expires_at.isoformat(),
            "raw_token": raw_token,
        }

    def invite_bulk_users(
        self,
        org_id: int,
        emails: List[str],
        role_id: int,
        invited_by_user: User,
        base_url: str = "http://localhost:3000",
    ) -> List[Dict[str, Any]]:
        """Refinement #2: Onboards multiple users in bulk."""
        results = []
        for email in emails:
            clean_email = email.strip()
            if clean_email:
                try:
                    res = self.invite_user(org_id, clean_email, role_id, invited_by_user, base_url)
                    results.append(res)
                except Exception as exc:
                    logger.warning(f"Failed to invite {clean_email}: {exc}")
        return results

    def accept_invitation(self, raw_token: str, user: User) -> Dict[str, Any]:
        """Refinement #3: Validates raw_token against SHA-256 token_hash in DB."""
        token_hash = self.hash_token(raw_token)
        inv = self.inv_repo.get_by_token_hash(token_hash)
        if not inv:
            raise HTTPException(status_code=404, detail="Invalid or expired invitation token.")
        if inv.status != "pending":
            raise HTTPException(status_code=400, detail=f"Invitation is already {inv.status}.")

        now = datetime.datetime.now(datetime.timezone.utc)
        if inv.expires_at < now:
            self.inv_repo.update_status(inv.id, "expired")
            raise HTTPException(status_code=400, detail="Invitation token has expired.")

        # Accept & bind user to Organization and Role
        self.org_repo.add_member(inv.organization_id, user.id)
        self.role_repo.assign_role_to_user(user.id, inv.role_id, inv.organization_id)
        self.inv_repo.update_status(inv.id, "accepted")

        from app.services.permission_service import PermissionService
        PermissionService.invalidate_cache_for_user(user.id)

        self.publisher.publish_event(
            action="Invitation Accepted",
            resource_type="OrganizationInvitation",
            category="Organization",
            user_id=user.id,
            organization_id=inv.organization_id,
            resource_id=str(inv.uuid),
        )

        return {"message": "Invitation accepted successfully.", "organization_id": inv.organization_id}
