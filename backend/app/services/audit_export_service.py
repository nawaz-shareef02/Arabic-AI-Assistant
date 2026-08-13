"""
AuditExportService — Refinement #9: Dedicated Export Architecture for CSV formatting.
"""

import io
import csv
import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.repositories.audit_repository import AuditRepository


class AuditExportService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AuditRepository(db)

    def generate_csv_export(
        self,
        org_id: Optional[int] = None,
        user_id: Optional[int] = None,
        category: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[datetime.datetime] = None,
        end_date: Optional[datetime.datetime] = None,
    ) -> str:
        logs, _ = self.repo.query_logs(
            org_id=org_id,
            user_id=user_id,
            category=category,
            action=action,
            start_date=start_date,
            end_date=end_date,
            page=1,
            page_size=10000,
        )

        output = io.StringIO()
        writer = csv.writer(output)

        # CSV Header
        writer.writerow([
            "Timestamp",
            "Category",
            "Action",
            "Resource Type",
            "Resource ID",
            "User ID",
            "User Email",
            "Organization ID",
            "Status",
            "Client IP",
            "Request ID",
        ])

        for log in logs:
            writer.writerow([
                log.timestamp.isoformat() if log.timestamp else "",
                log.category,
                log.action,
                log.resource_type,
                log.resource_id or "",
                log.user_id or "",
                log.user.email if log.user else "",
                log.organization_id or "",
                log.status,
                log.client_ip or "",
                log.request_id or "",
            ])

        return output.getvalue()
