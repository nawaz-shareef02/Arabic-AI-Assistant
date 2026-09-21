"""
OrganizationInvitationService — Enterprise Organization Invitation & Lifecycle Manager.

Guarantees:
1. Cryptographically secure random token generation (secrets.token_urlsafe(32)).
2. Token hash-only persistence (SHA-256) — raw tokens are NEVER stored in DB or logged.
3. Strict Tenant Isolation & Role Hierarchy Enforcement (anti-privilege-escalation).
4. Single-use token invalidation and atomic concurrency control (.with_for_update()).
5. Dual account flow: seamless acceptance for existing users and registration for new users.
6. Configurable invitation URLs with zero localhost hardcoding in production.
7. Audit event emission for all lifecycle transitions without secret leakage.
"""

import datetime
import hashlib
import logging
import re
import secrets
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, validate_password_strength, verify_password
from app.models.organization import OrganizationMember
from app.models.organization_invitation import OrganizationInvitation
from app.models.role import Role, UserRole
from app.models.user import User
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.role_repository import RoleRepository
from app.services.audit_event_publisher import AuditEventPublisher
from app.services.email_service import EmailService

logger = logging.getLogger("app.services.organization_invitation_service")

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _is_expired(expires_at: datetime.datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    return expires_at < datetime.datetime.now(datetime.timezone.utc)


class OrganizationInvitationService:
    def __init__(self, db: Session, email_service: Optional[EmailService] = None):
        self.db = db
        self.inv_repo = InvitationRepository(db)
        self.role_repo = RoleRepository(db)
        self.org_repo = OrganizationRepository(db)
        self.email_service = email_service or EmailService()
        self.publisher = AuditEventPublisher(db)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Computes SHA-256 hash of raw invitation token."""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def _validate_inviter_authority(
        self, inviter_user_id: int, org_id: int, target_role: Role
    ) -> None:
        """
        Enforces strict RBAC role hierarchy to prevent privilege escalation.
        - Super Admins can assign any role.
        - Organization Admins can assign Organization Admin, Knowledge Manager, Editor, AI User, Viewer.
        - Non-admins cannot grant roles higher than or equal to Super Admin.
        """
        user_roles = (
            self.db.query(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .filter(
                UserRole.user_id == inviter_user_id,
                (UserRole.organization_id == org_id) | (Role.is_system_role == True),
            )
            .all()
        )

        role_names = {r.name for r in user_roles}
        is_super_admin = "Super Admin" in role_names
        is_org_admin = "Organization Admin" in role_names or is_super_admin

        if not is_org_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to invite users to this organization.",
            )

        if target_role.name == "Super Admin" and not is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Administrators can grant Super Admin privileges.",
            )

    def invite_user(
        self,
        org_id: int,
        email: str,
        role_id: int,
        invited_by_user: User,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates an organization invitation, stores its SHA-256 hash, and dispatches email.
        """
        clean_email = email.lower().strip()
        if not clean_email or not EMAIL_REGEX.match(clean_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please provide a valid email address.",
            )

        org = self.org_repo.get_by_id(org_id)
        if not org or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found or inactive.",
            )

        target_role = (
            self.db.query(Role)
            .filter(
                Role.id == role_id,
                (Role.organization_id == org_id) | (Role.is_system_role == True),
            )
            .first()
        )
        if not target_role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role ID specified for this organization.",
            )

        # Enforce RBAC anti-privilege-escalation
        self._validate_inviter_authority(invited_by_user.id, org_id, target_role)

        # Check if user is already an active member of the organization
        existing_user = self.db.query(User).filter(User.email == clean_email).first()
        if existing_user:
            is_already_member = (
                self.db.query(OrganizationMember)
                .filter(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == existing_user.id,
                )
                .first()
                is not None
            )
            if is_already_member:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User {clean_email} is already a member of this organization.",
                )

        # Invalidate any existing active pending invitation for this (org, email) pair
        active_inv = self.inv_repo.get_active_by_org_and_email(org_id, clean_email)
        if active_inv:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            self.inv_repo.update_status(
                active_inv.id, "revoked", revoked_at=now_utc
            )

        # Generate cryptographically secure raw token and compute SHA-256 digest
        raw_token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(raw_token)
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=settings.INVITATION_TOKEN_EXPIRE_HOURS
        )

        inv = self.inv_repo.create(
            org_id=org_id,
            email=clean_email,
            role_id=role_id,
            token_hash=token_hash,
            invited_by_id=invited_by_user.id,
            expires_at=expires_at,
        )

        # Construct invitation link using resolved base URL
        resolved_base = (base_url or settings.resolved_invitation_base_url).rstrip("/")
        invitation_link = f"{resolved_base}/accept-invitation?token={raw_token}"

        # Dispatch transactional invitation email
        self.email_service.send_organization_invitation(
            to_email=clean_email,
            org_name=org.name,
            invitation_link=invitation_link,
            role_name=target_role.name,
            inviter_name=invited_by_user.full_name or invited_by_user.email,
        )

        # Audit event without exposing token
        self.publisher.publish_event(
            action="Invitation Sent",
            resource_type="OrganizationInvitation",
            category="Organization",
            user_id=invited_by_user.id,
            organization_id=org_id,
            resource_id=str(inv.uuid),
            metadata_json={"email": clean_email, "role": target_role.name},
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
        base_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Invites multiple users in bulk with batch size bounds."""
        if len(emails) > 50:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bulk invitations are limited to 50 recipients per batch.",
            )

        results = []
        for raw_email in emails:
            clean_email = raw_email.strip()
            if not clean_email:
                continue
            try:
                res = self.invite_user(
                    org_id=org_id,
                    email=clean_email,
                    role_id=role_id,
                    invited_by_user=invited_by_user,
                    base_url=base_url,
                )
                results.append({"email": clean_email, "status": "success", "data": res})
            except HTTPException as exc:
                results.append({"email": clean_email, "status": "error", "error": exc.detail})
            except Exception as exc:
                logger.warning(f"Failed to invite {clean_email}: {exc}")
                results.append({"email": clean_email, "status": "error", "error": "Internal processing error."})
        return results

    def verify_invitation(self, raw_token: str) -> Dict[str, Any]:
        """
        Public endpoint verifying invitation token validity and returning safe preview.
        """
        token_hash = self.hash_token(raw_token)
        inv = self.inv_repo.get_by_token_hash(token_hash)
        if not inv:
            return {
                "valid": False,
                "reason": "invalid",
                "detail": "Invalid or unknown invitation token.",
            }

        if inv.status != "pending":
            return {
                "valid": False,
                "reason": inv.status,
                "detail": f"This invitation has already been {inv.status}.",
            }

        if _is_expired(inv.expires_at):
            self.inv_repo.update_status(inv.id, "expired")
            return {
                "valid": False,
                "reason": "expired",
                "detail": "This invitation has expired.",
            }

        user_exists = (
            self.db.query(User).filter(User.email == inv.email).first() is not None
        )

        return {
            "valid": True,
            "email": inv.email,
            "organization_name": inv.organization.name if inv.organization else "Organization",
            "role_name": inv.role.name if inv.role else "Member",
            "expires_at": inv.expires_at.isoformat(),
            "user_exists": user_exists,
        }

    def accept_invitation(
        self,
        raw_token: str,
        current_user: Optional[User] = None,
        full_name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Atomically consumes an invitation, establishes user identity, and assigns membership.
        Protected against race conditions via DB row-level locking (.with_for_update()).
        """
        token_hash = self.hash_token(raw_token)
        inv = self.inv_repo.get_by_token_hash(token_hash, for_update=True)
        if not inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid or expired invitation token.",
            )

        if inv.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invitation is already {inv.status}.",
            )

        if _is_expired(inv.expires_at):
            self.inv_repo.update_status(inv.id, "expired")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation token has expired.",
            )

        now = datetime.datetime.now(datetime.timezone.utc)

        # Establish target user identity
        target_user: User
        if current_user is not None:
            # Authenticated acceptance: verify identity matches invitation
            if current_user.email.lower().strip() != inv.email.lower().strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"This invitation was sent to {inv.email}, but you are currently signed in as {current_user.email}.",
                )
            target_user = current_user
        else:
            # Unauthenticated acceptance: resolve existing vs new user
            existing_user = (
                self.db.query(User)
                .filter(User.email == inv.email.lower().strip())
                .first()
            )
            if existing_user:
                if not password:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="An account already exists for this email. Please provide your password or sign in.",
                    )
                if not verify_password(password, existing_user.hashed_password):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Incorrect password for existing account.",
                    )
                target_user = existing_user
            else:
                # Create new user account
                if not password:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Password is required to create your new account.",
                    )
                try:
                    validate_password_strength(password, inv.email, full_name or "User")
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=str(e),
                    )

                display_name = full_name.strip() if full_name and full_name.strip() else inv.email.split("@")[0]
                target_user = User(
                    email=inv.email.lower().strip(),
                    hashed_password=get_password_hash(password),
                    full_name=display_name,
                    organization=inv.organization.name if inv.organization else "Enterprise",
                    is_active=True,
                )
                self.db.add(target_user)
                self.db.flush()

        # Bind user to Organization and Role
        self.org_repo.add_member(inv.organization_id, target_user.id)
        self.role_repo.assign_role_to_user(
            user_id=target_user.id,
            role_id=inv.role_id,
            org_id=inv.organization_id,
        )

        # Mark invitation as consumed
        self.inv_repo.update_status(inv.id, "accepted", accepted_at=now)

        # Invalidate cached permissions for the target user
        from app.services.permission_service import PermissionService
        PermissionService.invalidate_cache_for_user(target_user.id)

        # Issue JWT Access Token for immediate authentication
        access_token = create_access_token(
            subject=target_user.email,
            additional_claims={
                "user_id": target_user.id,
                "org_id": inv.organization_id,
            },
        )

        # Record audit event
        self.publisher.publish_event(
            action="Invitation Accepted",
            resource_type="OrganizationInvitation",
            category="Organization",
            user_id=target_user.id,
            organization_id=inv.organization_id,
            resource_id=str(inv.uuid),
            metadata_json={"email": target_user.email, "role_id": inv.role_id},
        )

        return {
            "message": "Invitation accepted successfully.",
            "organization_id": inv.organization_id,
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": target_user.id,
                "email": target_user.email,
                "full_name": target_user.full_name,
            },
        }

    def cancel_invitation(
        self, inv_uuid: str, org_id: int, current_user: User
    ) -> Dict[str, Any]:
        """Cancels a pending invitation within the caller's organization."""
        inv = self.inv_repo.get_by_uuid(inv_uuid, org_id=org_id)
        if not inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found in this organization.",
            )

        if inv.status == "accepted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel an already accepted invitation.",
            )
        if inv.status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation is already cancelled.",
            )

        now = datetime.datetime.now(datetime.timezone.utc)
        self.inv_repo.update_status(inv.id, "cancelled", revoked_at=now)

        self.publisher.publish_event(
            action="Invitation Revoked",
            resource_type="OrganizationInvitation",
            category="Organization",
            user_id=current_user.id,
            organization_id=org_id,
            resource_id=str(inv.uuid),
            metadata_json={"email": inv.email},
        )

        return {
            "message": "Invitation cancelled successfully.",
            "uuid": str(inv.uuid),
        }

    def resend_invitation(
        self,
        inv_uuid: str,
        org_id: int,
        current_user: User,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resends an invitation with a freshly rotated secure token and reset expiration."""
        inv = self.inv_repo.get_by_uuid(inv_uuid, org_id=org_id)
        if not inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found in this organization.",
            )

        if inv.status == "accepted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot resend an already accepted invitation.",
            )

        raw_token = secrets.token_urlsafe(32)
        new_token_hash = self.hash_token(raw_token)
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(
            hours=settings.INVITATION_TOKEN_EXPIRE_HOURS
        )

        inv.token_hash = new_token_hash
        inv.status = "pending"
        inv.expires_at = expires_at
        inv.revoked_at = None
        self.db.commit()
        self.db.refresh(inv)

        resolved_base = (base_url or settings.resolved_invitation_base_url).rstrip("/")
        invitation_link = f"{resolved_base}/accept-invitation?token={raw_token}"

        self.email_service.send_organization_invitation(
            to_email=inv.email,
            org_name=inv.organization.name if inv.organization else "Organization",
            invitation_link=invitation_link,
            role_name=inv.role.name if inv.role else "Member",
            inviter_name=current_user.full_name or current_user.email,
        )

        self.publisher.publish_event(
            action="Invitation Sent",
            resource_type="OrganizationInvitation",
            category="Organization",
            user_id=current_user.id,
            organization_id=org_id,
            resource_id=str(inv.uuid),
            metadata_json={"email": inv.email, "resend": True},
        )

        return {
            "uuid": str(inv.uuid),
            "email": inv.email,
            "status": "pending",
            "expires_at": inv.expires_at.isoformat(),
            "raw_token": raw_token,
        }
