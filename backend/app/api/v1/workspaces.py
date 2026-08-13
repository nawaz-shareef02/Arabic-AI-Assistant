"""
Workspaces API Router — Optional Workspace Management Endpoints.

Endpoints
---------
POST /api/v1/workspaces/ — Create workspace
GET /api/v1/workspaces/  — List workspaces
"""

from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission, get_security_context
from app.core.security_context import SecurityContext
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["WORKSPACES"])


class WorkspaceCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""


@router.post("", summary="Create Workspace")
@router.post("/", summary="Create Workspace")
def create_workspace(
    req: WorkspaceCreateRequest,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("organizations.manage")),
):
    if not sec_ctx.org_id:
        raise HTTPException(status_code=400, detail="No active organization context found.")

    svc = WorkspaceService(db)
    ws = svc.create_workspace(
        org_id=sec_ctx.org_id,
        name=req.name,
        description=req.description or "",
        user_id=sec_ctx.user.id,
    )
    return {"id": ws.id, "uuid": str(ws.uuid), "name": ws.name, "description": ws.description}


@router.get("", summary="List Workspaces")
@router.get("/", summary="List Workspaces")
def list_workspaces(
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("knowledge_base.read")),
):
    if not sec_ctx.org_id:
        return []

    svc = WorkspaceService(db)
    workspaces = svc.list_workspaces(sec_ctx.org_id)
    return [
        {"id": w.id, "uuid": str(w.uuid), "name": w.name, "description": w.description}
        for w in workspaces
    ]
