"""
Organizations API Router — Multi-Tenant Organization Administration Endpoints.

Endpoints
---------
GET /api/v1/organizations/                    — List all enterprise organizations
GET /api/v1/organizations/me                  — Get current user's organizations & workspaces
GET /api/v1/organizations/{id}/members        — Get organization members
GET /api/v1/organizations/{id}/activity       — Get organization activity feed
GET /api/v1/organizations/invitations         — List organization's invitations
GET /api/v1/organizations/invitations/verify  — Verify invitation token validity (public)
POST /api/v1/organizations/invitations        — Invite single user
POST /api/v1/organizations/invitations/bulk   — Bulk invite users
POST /api/v1/organizations/invitations/accept — Accept invitation (public or authenticated)
POST /api/v1/organizations/invitations/{uuid}/cancel — Cancel pending invitation
POST /api/v1/organizations/invitations/{uuid}/resend — Resend invitation with fresh token
"""

from typing import List, Optional
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_db,
    get_current_user,
    get_optional_current_user,
    require_permission,
    get_security_context,
)
from app.core.cookies import set_auth_cookie, set_csrf_cookie, generate_csrf_token
from app.core.csrf import validate_origin
from app.core.security_context import SecurityContext
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.invitation_repository import InvitationRepository
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
    full_name: Optional[str] = None
    password: Optional[str] = None


@router.get("", summary="List All Organizations")
@router.get("/", summary="List All Organizations")
def list_organizations(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("organizations.manage")),
):
    org_repo = OrganizationRepository(db)
    orgs = org_repo.get_user_organizations(user.id)
    return [
        {
            "id": o.id,
            "uuid": str(o.uuid),
            "name": o.name,
            "slug": o.slug,
            "domain": o.domain,
            "is_active": o.is_active,
        }
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
                    {"id": w.id, "uuid": str(w.uuid), "name": w.name}
                    for w in o.workspaces
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
    if not sec_ctx.is_super_admin and sec_ctx.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot access members of another organization.",
        )
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
    if not sec_ctx.is_super_admin and sec_ctx.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot access activity of another organization.",
        )
    svc = OrganizationService(db)
    return svc.get_activity_feed(org_id, limit=limit)


@router.get("/invitations", summary="List Organization Invitations")
def list_invitations(
    status_filter: Optional[str] = Query(None, alias="status"),
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    if not sec_ctx.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization context found.",
        )

    inv_repo = InvitationRepository(db)
    invitations = inv_repo.get_all_by_org(sec_ctx.org_id, status=status_filter)
    return [
        {
            "id": inv.id,
            "uuid": str(inv.uuid),
            "email": inv.email,
            "role_id": inv.role_id,
            "role_name": inv.role.name if inv.role else "Member",
            "status": inv.status,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invitations
    ]


@router.get("/invitations/verify", summary="Verify Invitation Token Validity (Public)")
def verify_invitation_token(
    token: str = Query(..., description="Raw invitation token"),
    db: Session = Depends(get_db),
):
    svc = OrganizationInvitationService(db)
    return svc.verify_invitation(token)


@router.post("/invitations", summary="Invite Single User")
def invite_user(
    req: InviteUserRequest,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    if not sec_ctx.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization context found.",
        )

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
    if not sec_ctx.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization context found.",
        )

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
    fastapi_req: Request,
    response: Response,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Accept organization invitation (P2-1).
    Origin-protected against login-CSRF.
    Sets HttpOnly auth_token and non-HttpOnly csrf_token cookies on response.
    Returns safe user/organization payload without JWT in response body.
    """
    validate_origin(fastapi_req)
    svc = OrganizationInvitationService(db)
    res = svc.accept_invitation(
        raw_token=req.token,
        current_user=current_user,
        full_name=req.full_name,
        password=req.password,
    )

    access_token = res.get("access_token")
    if access_token:
        csrf_token = generate_csrf_token()
        set_auth_cookie(response, access_token)
        set_csrf_cookie(response, csrf_token)

    return {
        "message": res.get("message", "Invitation accepted successfully."),
        "organization_id": res.get("organization_id"),
        "user": res.get("user"),
    }


@router.post("/invitations/{inv_uuid}/cancel", summary="Cancel Pending Invitation")
def cancel_invitation(
    inv_uuid: str,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    if not sec_ctx.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization context found.",
        )

    svc = OrganizationInvitationService(db)
    return svc.cancel_invitation(
        inv_uuid=inv_uuid,
        org_id=sec_ctx.org_id,
        current_user=sec_ctx.user,
    )


@router.post("/invitations/{inv_uuid}/resend", summary="Resend Organization Invitation")
def resend_invitation(
    inv_uuid: str,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("users.manage")),
):
    if not sec_ctx.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization context found.",
        )

    svc = OrganizationInvitationService(db)
    return svc.resend_invitation(
        inv_uuid=inv_uuid,
        org_id=sec_ctx.org_id,
        current_user=sec_ctx.user,
    )
