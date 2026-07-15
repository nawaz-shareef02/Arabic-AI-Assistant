import uuid as py_uuid
import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator

class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="Unique email address of the user")
    password: str = Field(..., min_length=8, description="User password (minimum 8 characters)")
    full_name: str = Field(..., max_length=255, description="Full name of the user")
    organization: str = Field(..., max_length=255, description="User's enterprise organization name")
    preferred_language: Optional[str] = Field("en", max_length=10, description="Preferred interface language (e.g. en, ar)")

    @model_validator(mode="after")
    def check_password_strength(self) -> "RegisterRequest":
        from app.core.security import validate_password_strength
        try:
            validate_password_strength(self.password, self.email, self.full_name)
        except ValueError as e:
            raise ValueError(str(e))
        return self

    @field_validator("full_name", "organization")
    @classmethod
    def sanitize_inputs(cls, v: str) -> str:
        import html
        return html.escape(v.strip())

class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address used for logging in")
    password: str = Field(..., description="Secret user password")

class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token scheme type, defaults to bearer")

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: py_uuid.UUID = Field(..., description="Unique system UUID for the user")
    email: EmailStr = Field(..., description="Email address of the user")
    full_name: str = Field(..., description="Full name of the user")
    role: str = Field(..., description="User role, e.g. employee or admin")
    organization: str = Field(..., description="User's organization name")
    preferred_language: str = Field(..., description="User's preferred language")
    is_active: bool = Field(..., description="Indicates whether the user account is active")
    last_login: Optional[datetime.datetime] = Field(None, description="Timestamp of the user's last login")
    created_at: datetime.datetime = Field(..., description="User registration timestamp")
    updated_at: datetime.datetime = Field(..., description="User account last update timestamp")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address for password recovery")

