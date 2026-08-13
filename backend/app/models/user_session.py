import uuid as py_uuid
import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, Float, DateTime, ForeignKey, func, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserSession(Base):
    """
    UserSession Model — Refinements #1, #2, #4 & #9:
    SHA-256 Token Hashing, Device Fingerprinting, Risk Scoring, and Token Family Protection.
    """
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    family_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Refinement #2: Device Fingerprinting
    device_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # desktop, mobile, tablet
    browser: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    os: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # Refinement #4: Session Risk Scoring (0.0 to 1.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_active_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship()
