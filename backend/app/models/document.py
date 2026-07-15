import uuid as py_uuid
import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, func, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.parsed_document import ParsedDocument

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[py_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=py_uuid.uuid4,
        unique=True,
        index=True,
        nullable=False
    )
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(50), default=None, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="Queued", nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), default=None, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    parsed_document: Mapped[Optional["ParsedDocument"]] = relationship(
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan"
    )

    @property
    def pages(self) -> Optional[int]:
        return self.parsed_document.page_count if self.parsed_document else None

    @property
    def characters(self) -> Optional[int]:
        return self.parsed_document.char_count if self.parsed_document else None

    @property
    def processing_time(self) -> Optional[float]:
        if self.parsed_document:
            return round(self.parsed_document.processing_duration, 2)
        return None

    @property
    def parser_name(self) -> Optional[str]:
        return self.parsed_document.parser_version if self.parsed_document else None

    @property
    def parsed_document_id(self) -> Optional[int]:
        return self.parsed_document.id if self.parsed_document else None

    @property
    def knowledge_base_uuid(self) -> py_uuid.UUID:
        return self.knowledge_base.uuid
