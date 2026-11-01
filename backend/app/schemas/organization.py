import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrganizationUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    description: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    organization_type: str
    industry: str | None = None
    description: str | None = None
    city: str
    region: str | None = None
    country: str
    created_at: datetime
    updated_at: datetime
