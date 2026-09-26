"""
Organization Schemas — Quota Policies & Administration (AI-8 Phase B).
"""

from typing import Optional
from pydantic import BaseModel, Field


class OrganizationQuotaPolicy(BaseModel):
    """
    Organization quota policy representation (AI-8 Phase B).
    None represents unlimited quota.
    Values must be non-negative integers.
    """
    monthly_token_budget: Optional[int] = Field(
        default=None,
        ge=0,
        description="Monthly AI token budget (None = unlimited)",
    )
    max_storage_mb: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum document storage in MB (None = unlimited)",
    )
    max_documents: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum number of uploaded documents (None = unlimited)",
    )

    model_config = {"from_attributes": True}


class OrganizationQuotaUpdate(BaseModel):
    """
    Organization quota policy update payload (AI-8 Phase B).
    """
    monthly_token_budget: Optional[int] = Field(
        default=None,
        ge=0,
        description="Monthly AI token budget (None = unlimited)",
    )
    max_storage_mb: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum document storage in MB (None = unlimited)",
    )
    max_documents: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum number of uploaded documents (None = unlimited)",
    )
