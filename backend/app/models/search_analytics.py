import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.knowledge_base import KnowledgeBase


class SearchAnalytics(Base):
    __tablename__ = "search_analytics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunks_returned: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON, default=list, nullable=True
    )
    filters_used: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, default=dict, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship()
    knowledge_base: Mapped[Optional["KnowledgeBase"]] = relationship()
