import uuid as py_uuid
import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, Boolean, Integer, Float, JSON, DateTime, func, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class BackupRecord(Base):
    """
    BackupRecord Model — Refinements #1, #10 & #12:
    Backup History, Manifest File References, Checksums, Immutable Locking & Legal Hold.
    """
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False,
    )

    backup_type: Mapped[str] = mapped_column(String(50), default="Full", index=True, nullable=False)  # Full, Incremental, Differential, On-Demand, Component
    target: Mapped[str] = mapped_column(String(100), default="All", index=True, nullable=False)  # All, PostgreSQL, Qdrant, Redis, Storage, Audit, AI Benchmarks
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Refinement #1: Manifest File Path
    manifest_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Refinement #10: Immutable Locking & Legal Hold
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[str] = mapped_column(String(50), default="completed", index=True, nullable=False)  # running, completed, failed, verified
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    rto_seconds: Mapped[float] = mapped_column(Float, default=120.0, nullable=False)
    rpo_seconds: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)

    manifest_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
