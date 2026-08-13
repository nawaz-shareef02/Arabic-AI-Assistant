"""
AuditEventPublisher — Refinement #1: Event Bus Abstraction Layer.

Decouples API & Middleware from audit log persistence.
Forwards audit payload dictionaries to AuditService or async queue handlers.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger("app.services.audit_event_publisher")


class AuditEventPublisher:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AuditRepository(db)

    def publish_event(
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
    ) -> None:
        """Publishes an audit event to the append-only persistence layer."""
        try:
            self.repo.create(
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
                metadata_json=metadata_json,
            )
        except Exception as exc:
            logger.error(f"AuditEventPublisher: Failed to publish event {action}: {exc}")
