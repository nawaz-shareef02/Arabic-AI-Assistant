"""
Roles API Router — Role-Based Access Control Management Endpoints.

Endpoints
---------
GET /api/v1/roles/            — List enterprise system & custom roles
GET /api/v1/roles/permissions — List all system dot-notation permissions
POST /api/v1/roles/assign    — Assign role to user
"""

from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission, get_security_context
from app.core.security_context import SecurityContext
from app.repositories.role_repository import RoleRepository
from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import PermissionService

from app.models.organization import OrganizationMember

router = APIRouter(prefix="/roles", tags=["ROLES"])


class RoleAssignRequest(BaseModel):
    user_id: int
    role_id: int
    organization_id: Optional[int] = None


@router.get("", summary="List Roles")
@router.get("/", summary="List Roles")
def list_roles(
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("roles.manage")),
):
    role_repo = RoleRepository(db)
    roles = role_repo.get_all(org_id=sec_ctx.org_id)
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "is_system_role": r.is_system_role,
            "organization_id": r.organization_id,
        }
        for r in roles
    ]


@router.get("/permissions", summary="List All Permissions")
def list_permissions(
    db: Session = Depends(get_db),
    user=Depends(require_permission("roles.manage")),
):
    perm_repo = PermissionRepository(db)
    perms = perm_repo.get_all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "resource": p.resource,
            "action": p.action,
            "description": p.description,
        }
        for p in perms
    ]


@router.post("/assign", summary="Assign Role to User")
def assign_role(
    req: RoleAssignRequest,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("roles.manage")),
):
    role_repo = RoleRepository(db)
    target_role = role_repo.get_by_id(req.role_id)
    if not target_role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found.",
        )

    if not sec_ctx.is_super_admin:
        # SEC-REQ-01: Non-Super-Admin callers must NOT be able to assign system roles such as Super Admin
        has_system_admin_perm = any(
            rp.permission and rp.permission.name == "system.admin"
            for rp in target_role.permissions_associations
        )
        if target_role.name == "Super Admin" or has_system_admin_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Administrators can assign system administrator roles.",
            )

        # SEC-REQ-01: Non-Super-Admin callers must NOT assign roles into another organization
        if req.organization_id is not None and req.organization_id != sec_ctx.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: You cannot assign roles into another organization.",
            )

        if not sec_ctx.org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active organization context found.",
            )

        target_org_id = sec_ctx.org_id

        # Target user must belong to caller's organization
        is_member = (
            db.query(OrganizationMember)
            .filter(
                OrganizationMember.organization_id == target_org_id,
                OrganizationMember.user_id == req.user_id,
            )
            .first()
        )
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: Target user is not a member of your organization.",
            )
    else:
        # Legitimate Super Admin role assignment
        target_org_id = req.organization_id

    user_role = role_repo.assign_role_to_user(req.user_id, req.role_id, target_org_id)
    PermissionService.invalidate_cache_for_user(req.user_id)

    return {
        "message": f"Successfully assigned role {req.role_id} to user {req.user_id}",
        "user_role_id": user_role.id,
    }
