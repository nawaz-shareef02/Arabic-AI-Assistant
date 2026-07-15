import uuid as py_uuid
import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class RecentActivityItem(BaseModel):
    uuid: py_uuid.UUID = Field(..., description="Document UUID")
    filename: str = Field(..., description="Document filename")
    mime_type: str = Field(..., description="Mime type")
    status: str = Field(..., description="Processing status")
    created_at: datetime.datetime = Field(..., description="Upload timestamp")
    kb_name: str = Field(..., description="Parent Knowledge Base Name")
    kb_uuid: py_uuid.UUID = Field(..., description="Parent Knowledge Base UUID")

class DashboardSummaryResponse(BaseModel):
    knowledge_bases: int = Field(..., description="Total active knowledge bases count")
    documents: int = Field(..., description="Total documents count")
    storage_used: int = Field(..., description="Storage used in bytes")
    storage_used_mb: float = Field(..., description="Storage used in MB")
    last_upload: Optional[datetime.datetime] = Field(None, description="Timestamp of the last uploaded document")
    recent_activity: List[RecentActivityItem] = Field(default=[], description="List of recent activities")
    uploaded_docs: int = Field(..., description="Total uploaded documents waiting for processing")
    parsing_docs: int = Field(..., description="Total documents currently being parsed")
    parsed_docs: int = Field(..., description="Total successfully parsed documents")
    failed_docs: int = Field(..., description="Total documents that failed parsing")

