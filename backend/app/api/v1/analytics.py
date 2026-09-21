"""
Analytics API Router — Enterprise Knowledge & System Telemetry Services.

Endpoints
---------
GET /api/v1/analytics/summary — Full analytics metrics
GET /api/v1/analytics/health  — Knowledge base multi-dimensional health score
GET /api/v1/analytics/entities — Top extracted entities & category distribution
"""

from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission, get_security_context
from app.core.security_context import SecurityContext
from app.services.analytics_service import AnalyticsService
from app.services.knowledge_health_service import KnowledgeHealthService

router = APIRouter(prefix="/analytics", tags=["ANALYTICS"])


@router.get("/", summary="Analytics Overview")
@router.get("/summary", summary="Get Full Analytics Summary")
def get_analytics_summary(
    org_id: Optional[int] = None,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    svc = AnalyticsService(db)
    # SEC-REQ-03: Non-Super-Admin callers are strictly scoped to their own organization
    effective_org_id = org_id if sec_ctx.is_super_admin else sec_ctx.org_id
    return svc.get_full_analytics(org_id=effective_org_id)


@router.get("/health", summary="Get Knowledge Base Health Report")
def get_knowledge_health(
    knowledge_base_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    svc = KnowledgeHealthService(db)
    return svc.calculate_health(knowledge_base_id)


@router.get("/entities", summary="Get Top Entities & Category Breakdown")
def get_top_entities(
    org_id: Optional[int] = None,
    sec_ctx: SecurityContext = Depends(get_security_context),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analytics.view")),
):
    svc = AnalyticsService(db)
    effective_org_id = org_id if sec_ctx.is_super_admin else sec_ctx.org_id
    metrics = svc.knowledge_analytics.get_knowledge_metrics(org_id=effective_org_id)
    return {
        "top_entities": metrics["top_entities"],
        "category_distribution": metrics["category_distribution"],
    }