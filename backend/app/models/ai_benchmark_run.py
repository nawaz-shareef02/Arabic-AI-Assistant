import uuid as py_uuid
import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, JSON, DateTime, func, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class AIBenchmarkRun(Base):
    """
    AIBenchmarkRun Model — Refinements #1, #2, #9 & #12:
    Versioned Benchmark Run History, Profiles, Scorecards & Performance Reports.
    """
    __tablename__ = "ai_benchmark_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False,
    )

    # Refinement #1: Versioning
    dataset_version: Mapped[str] = mapped_column(String(50), default="1.0.0", index=True, nullable=False)
    benchmark_version: Mapped[str] = mapped_column(String(50), default="1.0.0", index=True, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(50), default="14.6.0", nullable=False)

    # Refinement #2: Profile Name (Quick, Standard, Full Regression, Production Validation)
    profile_name: Mapped[str] = mapped_column(String(50), default="Standard", index=True, nullable=False)

    metrics_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)
    scorecard_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)
    recommendations_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="completed", index=True, nullable=False)  # running, completed, failed
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
