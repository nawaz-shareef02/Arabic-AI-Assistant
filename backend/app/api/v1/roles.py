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
    db: Session = Depends(get_db),
    user=Depends(require_permission("roles.manage")),
):
    role_repo = RoleRepository(db)
    user_role = role_repo.assign_role_to_user(req.user_id, req.role_id, req.organization_id)
    PermissionService.invalidate_cache_for_user(req.user_id)

    return {
        "message": f"Successfully assigned role {req.role_id} to user {req.user_id}",
        "user_role_id": user_role.id,
    }
