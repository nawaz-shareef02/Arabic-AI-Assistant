"""
AuditMiddleware — Refinement #6: Automatic HTTP Audit Logging & Correlation ID Propagation.

Intercepts mutating API calls (POST, PUT, PATCH, DELETE) to publish categorized audit events.
"""

import time
import uuid
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.database.session import SessionLocal
from app.services.audit_event_publisher import AuditEventPublisher

logger = logging.getLogger("app.middleware.audit_middleware")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Propagate correlation_id and request_id
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - t0) * 1000)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        # 2. Automatically log mutating API endpoints
        path = request.url.path
        if request.method in ["POST", "PUT", "PATCH", "DELETE"] and path.startswith("/api/v1/"):
            # Avoid logging login/token request bodies or secrets
            if not ("/auth/login" in path or "/auth/token" in path):
                user_id = getattr(request.state, "user_id", None)
                org_id = getattr(request.state, "org_id", None)

                category = "System"
                if "/organizations" in path:
                    category = "Organization"
                elif "/workspaces" in path:
                    category = "Workspace"
                elif "/documents" in path:
                    category = "Document"
                elif "/knowledge-bases" in path:
                    category = "Knowledge Base"
                elif "/chat" in path:
                    category = "Chat"
                elif "/roles" in path:
                    category = "Administration"

                client_ip = request.client.host if request.client else "unknown"
                user_agent = request.headers.get("user-agent", "")[:255]
                status_str = "success" if response.status_code < 400 else "failure"

                # Publish asynchronously using a temporary session
                try:
                    db = SessionLocal()
                    publisher = AuditEventPublisher(db)
                    publisher.publish_event(
                        action=f"HTTP {request.method} {path}",
                        resource_type="API",
                        category=category,
                        user_id=user_id,
                        organization_id=org_id,
                        http_method=request.method,
                        api_endpoint=path,
                        client_ip=client_ip,
                        user_agent=user_agent,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        status=status_str,
                        metadata_json={"duration_ms": duration_ms, "status_code": response.status_code},
                    )
                    db.close()
                except Exception as exc:
                    logger.warning(f"AuditMiddleware failed to log request: {exc}")

        return response
