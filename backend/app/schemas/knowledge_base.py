import uuid as py_uuid
import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class KnowledgeBaseBase(BaseModel):
    name: str = Field(..., max_length=255, description="Name of the knowledge base")
    description: Optional[str] = Field(None, max_length=1000, description="Description of the knowledge base")

class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass

class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255, description="Updated name of the knowledge base")
    description: Optional[str] = Field(None, max_length=1000, description="Updated description of the knowledge base")

class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Database integer ID of the knowledge base")
    uuid: py_uuid.UUID = Field(..., description="Public UUID of the knowledge base")
    name: str = Field(..., description="Name of the knowledge base")
    description: Optional[str] = Field(None, description="Description of the knowledge base")
    is_active: bool = Field(..., description="Active status (false indicates soft deleted)")
    created_by: Optional[int] = Field(None, description="User ID of creator")
    updated_by: Optional[int] = Field(None, description="User ID of last updater")
    created_at: datetime.datetime = Field(..., description="Creation timestamp")
    updated_at: datetime.datetime = Field(..., description="Last update timestamp")
