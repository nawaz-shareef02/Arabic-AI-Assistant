"""
AuthorizationService — Enterprise Authorization & Policy Enforcement Service.

Refinement #7: Super Admin Bypass — Super Admin / system.admin automatically allowed.
Refinement #3: Policy Engine Extension — Room for future ABAC / time / IP policy rules.
Refinement #9: Authorization Audit Logging Hooks — Logs every access decision.
"""

import logging
from typing import Optional, Set
from sqlalchemy.orm import Session
from app.models.user import User
from app.services.permission_service import PermissionService

logger = logging.getLogger("app.services.authorization_service")


class AuthorizationService:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def log_authorization_decision(
        self,
        user_id: int,
        required_permission: str,
        resource: str,
        allowed: bool,
        reason: str,
    ) -> None:
        """Refinement #9: Audit logging hook for authorization decisions."""
        status_str = "GRANTED" if allowed else "DENIED"
        logger.info(
            f"AUDIT_RBAC | User: {user_id} | Resource: {resource} | "
            f"Permission: {required_permission} | Decision: {status_str} | Reason: {reason}"
        )

    def is_super_admin(self, user: User, permissions: Set[str]) -> bool:
        """Refinement #7: Super Admin check."""
        if "system.admin" in permissions:
            return True
        for ur in user.role_assignments:
            if ur.role and ur.role.name == "Super Admin":
                return True
        return False

    def evaluate_policy_rules(
        self,
        user: User,
        required_permission: str,
        org_id: Optional[int] = None,
    ) -> bool:
        """
        Refinement #3: Policy Engine Extensibility Hook.
        Placeholder for future ABAC, office hours, IP restrictions, department rules.
        """
        # Default policy: Organization isolation check if org_id is specified
        if org_id is not None and user.organization_memberships:
            user_org_ids = {m.organization_id for m in user.organization_memberships}
            if org_id not in user_org_ids:
                return False
        return True

    def check_permission(
        self,
        user: User,
        required_permission: str,
        org_id: Optional[int] = None,
    ) -> bool:
        """
        Enforces granular authorization check with Super Admin bypass,
        policy evaluation, and structured audit logging hooks.
        """
        user_perms = self.permission_service.get_user_permissions(user.id)

        # 1. Refinement #7: Super Admin Bypass
        if self.is_super_admin(user, user_perms):
            self.log_authorization_decision(
                user.id, required_permission, "api", True, "Super Admin Bypass"
            )
            return True

        # 2. Granular Permission Check
        has_perm = required_permission in user_perms
        if not has_perm:
            self.log_authorization_decision(
                user.id, required_permission, "api", False, f"Missing permission {required_permission}"
            )
            return False

        # 3. Policy Layer Evaluation
        policy_allowed = self.evaluate_policy_rules(user, required_permission, org_id)
        if not policy_allowed:
            self.log_authorization_decision(
                user.id, required_permission, "api", False, "Policy restriction (Organization mismatch)"
            )
            return False

        self.log_authorization_decision(
            user.id, required_permission, "api", True, "Granted by RBAC role assignment"
        )
        return True
