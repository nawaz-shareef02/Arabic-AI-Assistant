"""
Organizations API Router — Multi-Tenant Organization Administration Endpoints.

Endpoints
---------
GET /api/v1/organizations/                    — List all enterprise organizations
GET /api/v1/organizations/me                  — Get current user's organizations & workspaces
GET /api/v1/organizations/{id}/members        — Get organization members
GET /api/v1/organizations/{id}/activity       — Get organization activity feed (Refinement #10)
POST /api/v1/organizations/invitations        — Invite single user
POST /api/v1/organizations/invitations/bulk   — Bulk invite users (Refinement #2)
POST /api/v1/organizations/invitations/accept — Accept invitation (Refinement #3)
"""

from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user, require_permission, get_security_context
from app.core.security_context import SecurityContext
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.services.organization_service import OrganizationService
from app.services.organization_invitation_service import OrganizationInvitationService

router = APIRouter(prefix="/organizations", tags=["ORGANIZATIONS"])


class InviteUserRequest(BaseModel):
    email: str
    role_id: int


class BulkInviteUserRequest(BaseModel):
    emails: List[str]
    role_id: int


class AcceptInvitationRequest(BaseModel):
    token: str


@router.get("", summary="List All Organizations")
@router.get("/", summary="List All Organizations")
def list_organizations(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("organizations.manage")),
):
    org_repo = OrganizationRepository(db)
    orgs = org_repo.get_user_organizations(user.id)
    return [
        {"id": o.id, "uuid": str(o.uuid), "name": o.name, "slug": o.slug, "domain": o.domain, "is_active": o.is_active}
        for o in orgs
    ]


@router.get("/me", summary="Get My Organizations & Workspaces")
def get_my_organization(
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
):
    org_repo = OrganizationRepository(db)
    orgs = org_repo.get_user_organizations(sec_ctx.user.id)
    return {
        "user_id": sec_ctx.user.id,
        "email": sec_ctx.user.email,
        "current_org_id": sec_ctx.org_id,
        "organizations": [
            {
                "id": o.id,
                "uuid": str(o.uuid),
                "name": o.name,
                "slug": o.slug,
                "workspaces": [
                    {"id": w.id, "uuid": str(w.uuid), "name": w.name} for w in o.workspaces
                ],
            }
            for o in orgs
        ],
        "roles": sec_ctx.role_ids,
        "permissions": list(sec_ctx.permissions),
    }


@router.get("/{org_id}/members", summary="Get Organization Members")
def get_organization_members(
    org_id: int,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    svc = OrganizationService(db)
    return svc.get_organization_members(org_id)


@router.get("/{org_id}/activity", summary="Get Organization Activity Feed")
def get_organization_activity(
    org_id: int,
    limit: int = 50,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    """Refinement #10: Organization Activity Timeline Feed (Recent 50 Events)."""
    svc = OrganizationService(db)
    return svc.get_activity_feed(org_id, limit=limit)


@router.post("/invitations", summary="Invite Single User")
def invite_user(
    req: InviteUserRequest,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    if not sec_ctx.org_id:
        raise HTTPException(status_code=400, detail="No active organization context found.")

    svc = OrganizationInvitationService(db)
    return svc.invite_user(
        org_id=sec_ctx.org_id,
        email=req.email,
        role_id=req.role_id,
        invited_by_user=sec_ctx.user,
    )


@router.post("/invitations/bulk", summary="Bulk Invite Users")
def invite_bulk_users(
    req: BulkInviteUserRequest,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    """Refinement #2: Onboards multiple users in bulk."""
    if not sec_ctx.org_id:
        raise HTTPException(status_code=400, detail="No active organization context found.")

    svc = OrganizationInvitationService(db)
    return svc.invite_bulk_users(
        org_id=sec_ctx.org_id,
        emails=req.emails,
        role_id=req.role_id,
        invited_by_user=sec_ctx.user,
    )


@router.post("/invitations/accept", summary="Accept Organization Invitation")
def accept_invitation(
    req: AcceptInvitationRequest,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
):
    """Refinement #3: Validates raw_token against SHA-256 token_hash in DB."""
    svc = OrganizationInvitationService(db)
    return svc.accept_invitation(req.token, sec_ctx.user)
