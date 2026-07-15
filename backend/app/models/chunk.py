from uuid import uuid4
from datetime import datetime

from sqlalchemy import Integer, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)

    uuid: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid4,
        unique=True,
        nullable=False,
    )

    parsed_document_id: Mapped[int] = mapped_column(
        ForeignKey("parsed_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(Integer)

    chunk_text: Mapped[str] = mapped_column(Text)

    char_count: Mapped[int] = mapped_column(Integer)

    estimated_tokens: Mapped[int] = mapped_column(Integer)

    start_offset: Mapped[int] = mapped_column(Integer)

    end_offset: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    parsed_document = relationship(
        "ParsedDocument",
        back_populates="chunks",
    )