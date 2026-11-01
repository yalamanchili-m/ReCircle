from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_PROVENANCE = ("user_provided", "source_derived", "ai_inferred", "unverified")


class PassportAttribute(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: Any = None
    provenance: Literal[
        "user_provided", "source_derived", "ai_inferred", "unverified"
    ] = "user_provided"
    confidence: float | None = Field(default=None, ge=0, le=1)


class PassportCreate(BaseModel):
    notes: str | None = None


class PassportUpdate(BaseModel):
    """Creates a new passport version; previous versions become superseded."""

    attributes: dict[str, PassportAttribute] | None = None
    possible_applications: list[str] | None = Field(default=None, max_length=25)
    suitable_industries: list[str] | None = Field(default=None, max_length=25)
    candidate_pathways: list[str] | None = Field(default=None, max_length=25)
    notes: str | None = None

    @field_validator("possible_applications", "suitable_industries", "candidate_pathways")
    @classmethod
    def entries_must_be_short_strings(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [entry.strip() for entry in value if entry.strip()]
        for entry in cleaned:
            if len(entry) > 120:
                raise ValueError("list entries must be at most 120 characters")
        return cleaned


class PassportReview(BaseModel):
    review_status: Literal["reviewed", "unreviewed"]


class PassportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    listing_id: UUID
    organization_id: UUID
    version: int
    status: str
    attributes: dict[str, Any]
    possible_applications: list[str]
    suitable_industries: list[str]
    candidate_pathways: list[str]
    notes: str | None
    review_status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_by: UUID | None
    created_at: datetime


class PassportPublicResponse(PassportResponse):
    """Read-only passport view shown in the marketplace (active listings only)."""
