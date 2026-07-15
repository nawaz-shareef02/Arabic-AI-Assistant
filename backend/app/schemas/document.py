import uuid as py_uuid
import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator

class DocumentStatus(str, Enum):
    UPLOADED = "Uploaded"
    PENDING_SCAN = "Pending Scan"
    READY_FOR_PARSING = "Ready for Parsing"
    QUEUED = "Queued"
    PARSING = "Parsing"
    PARSED = "Parsed"
    CHUNKING = "Chunking"
    READY = "Ready"
    FAILED = "Failed"

class DocumentBase(BaseModel):
    filename: str = Field(..., max_length=255, description="Filename of the document")
    storage_path: str = Field(..., max_length=1024, description="Physical path or URI where file is stored")
    mime_type: str = Field(..., max_length=100, description="Mime type of the document (e.g. application/pdf)")
    file_size: int = Field(..., description="File size in bytes")
    language: Optional[str] = Field(None, max_length=50, description="Document main language (e.g. en, ar)")

class DocumentCreate(DocumentBase):
    knowledge_base_uuid: py_uuid.UUID = Field(..., description="UUID of the parent Knowledge Base")

class DocumentUpdate(BaseModel):
    filename: Optional[str] = Field(None, max_length=255, description="New filename of the document")
    knowledge_base_uuid: Optional[py_uuid.UUID] = Field(None, description="New Knowledge Base UUID if moving document")
    language: Optional[str] = Field(None, max_length=50, description="Updated main language")
    status: Optional[DocumentStatus] = Field(None, description="Updated processing status")

class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Database integer ID of the document")
    parsed_document_id: Optional[int] = Field(None, description="Database integer ID of the parsed document")
    uuid: py_uuid.UUID = Field(..., description="Public UUID of the document")
    knowledge_base_uuid: py_uuid.UUID = Field(..., description="UUID of the parent Knowledge Base")
    filename: str = Field(..., description="Filename of the document")
    storage_path: str = Field(..., description="Physical path or URI where file is stored")
    mime_type: str = Field(..., description="Mime type of the document")
    language: Optional[str] = Field(None, description="Document main language")
    status: DocumentStatus = Field(..., description="Processing status of the document")
    file_size: int = Field(..., description="File size in bytes")
    chunk_count: int = Field(..., description="Number of parsed text chunks")
    sha256_hash: Optional[str] = Field(None, description="SHA-256 hash checksum of the file")
    error_message: Optional[str] = Field(None, description="Detailed failure message if status is Failed")
    pages: Optional[int] = Field(None, description="Page count of parsed document")
    characters: Optional[int] = Field(None, description="Character count of parsed document")
    processing_time: Optional[float] = Field(None, description="Processing duration in seconds")
    parser_name: Optional[str] = Field(None, description="Class name of backend parser used")
    created_by: Optional[int] = Field(None, description="User ID of creator")
    updated_by: Optional[int] = Field(None, description="User ID of last updater")
    created_at: datetime.datetime = Field(..., description="Creation timestamp")
    updated_at: datetime.datetime = Field(..., description="Last update timestamp")
