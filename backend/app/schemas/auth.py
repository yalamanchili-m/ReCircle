import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginRequest(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "UserSummary"


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    organization_type: str
    industry: str | None = None
    description: str | None = None
    city: str
    region: str | None = None
    country: str


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str = Field(pattern=EMAIL_PATTERN)
    full_name: str
    role: str
    is_active: bool
    organization: OrganizationSummary | None = None


class TokenPayload(BaseModel):
    sub: str
    role: str
