"""
Audit API Router — Enterprise Compliance & Audit Logging Endpoints.

Endpoints
---------
GET /api/v1/audit/       — Query & filter categorized audit events
GET /api/v1/audit/export — Streaming CSV export of audit records (Refinement #9)
GET /api/v1/audit/{id}   — Detailed view of specific audit entry
"""

import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission, get_security_context
from app.core.security_context import SecurityContext
from app.services.audit_service import AuditService
from app.services.audit_export_service import AuditExportService

router = APIRouter(prefix="/audit", tags=["AUDIT"])


@router.get("", summary="Search Audit Logs")
@router.get("/", summary="Search Audit Logs")
def search_audit_logs(
    user_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    svc = AuditService(db)
    items, total = svc.search_audit_logs(
        org_id=sec_ctx.org_id,
        user_id=user_id,
        category=category,
        action=action,
        resource_type=resource_type,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/export", summary="Export Audit Logs as CSV")
def export_audit_csv(
    user_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    export_svc = AuditExportService(db)
    csv_content = export_svc.generate_csv_export(
        org_id=sec_ctx.org_id,
        user_id=user_id,
        category=category,
        action=action,
    )

    filename = f"arabiq_audit_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{log_id}", summary="Get Audit Log Entry Details")
def get_audit_log(
    log_id: int,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    svc = AuditService(db)
    log_data = svc.get_log_details(log_id)
    if not log_data:
        raise HTTPException(status_code=404, detail="Audit log entry not found.")
    return log_data
