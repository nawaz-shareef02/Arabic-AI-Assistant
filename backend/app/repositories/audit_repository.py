"""
AuditRepository — Append-Only Immutable Data Access for System Audit Logs.
"""

import datetime
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        action: str,
        resource_type: str,
        category: str = "System",
        user_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        workspace_id: Optional[int] = None,
        resource_id: Optional[str] = None,
        http_method: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        status: str = "success",
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """Appends an immutable audit log record."""
        entry = AuditLog(
            action=action,
            resource_type=resource_type,
            category=category,
            user_id=user_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            resource_id=resource_id,
            http_method=http_method,
            api_endpoint=api_endpoint,
            client_ip=client_ip,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
            status=status,
            metadata_json=metadata_json or {},
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def query_logs(
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
    ) -> Tuple[List[AuditLog], int]:
        query = self.db.query(AuditLog)

        if org_id is not None:
            query = query.filter(AuditLog.organization_id == org_id)
        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)
        if category:
            query = query.filter(AuditLog.category == category)
        if action:
            query = query.filter(AuditLog.action == action)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)
        if status_filter:
            query = query.filter(AuditLog.status == status_filter)
        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)

        total = query.count()
        results = (
            query.order_by(AuditLog.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return results, total

    def get_by_id(self, log_id: int) -> Optional[AuditLog]:
        return self.db.query(AuditLog).filter(AuditLog.id == log_id).first()
