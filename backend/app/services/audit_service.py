"""
AuditService — High-Level Enterprise Audit Log Query & Compliance Service.
"""

import datetime
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from app.repositories.audit_repository import AuditRepository


class AuditService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AuditRepository(db)

    def search_audit_logs(
        self,
        org_id: Optional[int] = None,
        user_id: Optional[int] = None,
        category: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        start_date: Optional[datetime.datetime] = None,
        end_date: Optional[datetime.datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        logs, total = self.repo.query_logs(
            org_id=org_id,
            user_id=user_id,
            category=category,
            action=action,
            resource_type=resource_type,
            status_filter=status_filter,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        items = [
            {
                "id": log.id,
                "uuid": str(log.uuid),
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "user_id": log.user_id,
                "user_email": log.user.email if log.user else None,
                "organization_id": log.organization_id,
                "workspace_id": log.workspace_id,
                "category": log.category,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "http_method": log.http_method,
                "api_endpoint": log.api_endpoint,
                "client_ip": log.client_ip,
                "request_id": log.request_id,
                "correlation_id": log.correlation_id,
                "status": log.status,
                "metadata": log.metadata_json,
            }
            for log in logs
        ]
        return items, total

    def get_log_details(self, log_id: int) -> Optional[Dict[str, Any]]:
        log = self.repo.get_by_id(log_id)
        if not log:
            return None
        return {
            "id": log.id,
            "uuid": str(log.uuid),
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "user_id": log.user_id,
            "user_email": log.user.email if log.user else None,
            "organization_id": log.organization_id,
            "workspace_id": log.workspace_id,
            "category": log.category,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "http_method": log.http_method,
            "api_endpoint": log.api_endpoint,
            "client_ip": log.client_ip,
            "user_agent": log.user_agent,
            "request_id": log.request_id,
            "correlation_id": log.correlation_id,
            "status": log.status,
            "metadata": log.metadata_json,
        }
