import uuid as py_uuid
import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, DateTime, ForeignKey, JSON, Index, func, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.organization import Organization


class AuditLog(Base):
    """
    AuditLog Model — Refinement #5 & #8: Categorized, Immutable Append-Only Audit Trail
    with composite indices for enterprise compliance & observability.
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False,
    )
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )

    category: Mapped[str] = mapped_column(String(50), default="System", index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    http_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    api_endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    request_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="success", index=True, nullable=False)  # success, failure, denied
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship()
    organization: Mapped[Optional["Organization"]] = relationship()

    # Refinement #8: Composite indices for high-volume audit performance
    __table_args__ = (
        Index("ix_audit_logs_org_ts", "organization_id", "timestamp"),
        Index("ix_audit_logs_user_ts", "user_id", "timestamp"),
        Index("ix_audit_logs_action_ts", "action", "timestamp"),
        Index("ix_audit_logs_res_ts", "resource_type", "timestamp"),
    )
