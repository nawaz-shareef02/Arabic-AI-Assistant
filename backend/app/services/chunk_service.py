from typing import List

from sqlalchemy.orm import Session

from app.models.chunk import DocumentChunk
from app.models.parsed_document import ParsedDocument


class ChunkService:
    """
    Enterprise document chunking service.
    """

    def __init__(
        self,
        db: Session = None,
        chunk_size: int = 900,
        overlap: int = 150,
    ):
        self.db = db
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split_text(self, text: str) -> List[dict]:

        if not text:
            return []

        chunks = []

        start = 0
        index = 1

        while start < len(text):

            end = min(start + self.chunk_size, len(text))

            chunk_text = text[start:end]

            chunks.append(
                {
                    "chunk_index": index,
                    "chunk_text": chunk_text,
                    "char_count": len(chunk_text),
                    "estimated_tokens": max(
                        1,
                        len(chunk_text) // 4,
                    ),
                    "start_offset": start,
                    "end_offset": end,
                }
            )

            start += self.chunk_size - self.overlap
            index += 1

        return chunks

    def create_chunks(self, parsed_document: ParsedDocument) -> int:
        """
        Save chunks into PostgreSQL.
        """

        chunks = self.split_text(parsed_document.parsed_text)

        for chunk in chunks:

            db_chunk = DocumentChunk(
                parsed_document_id=parsed_document.id,
                chunk_index=chunk["chunk_index"],
                chunk_text=chunk["chunk_text"],
                char_count=chunk["char_count"],
                estimated_tokens=chunk["estimated_tokens"],
                start_offset=chunk["start_offset"],
                end_offset=chunk["end_offset"],
            )

            self.db.add(db_chunk)

        self.db.commit()

        return len(chunks)