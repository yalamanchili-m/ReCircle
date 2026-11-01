from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import MATERIAL_CATEGORIES, REQUIREMENT_STATUSES, UNITS


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    category: str
    description: str | None = None
    min_quantity: Decimal = Field(gt=0)
    unit: str
    required_grade: str | None = Field(default=None, max_length=100)
    max_price_per_unit: Decimal | None = Field(default=None, ge=0)
    preferred_city: str | None = Field(default=None, max_length=100)
    preferred_region: str | None = Field(default=None, max_length=100)

    @field_validator("category")
    @classmethod
    def category_must_be_supported(cls, value: str) -> str:
        if value not in MATERIAL_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(MATERIAL_CATEGORIES)}")
        return value

    @field_validator("unit")
    @classmethod
    def unit_must_be_supported(cls, value: str) -> str:
        if value not in UNITS:
            raise ValueError(f"unit must be one of: {', '.join(UNITS)}")
        return value


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    category: str | None = None
    description: str | None = None
    min_quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None
    required_grade: str | None = None
    max_price_per_unit: Decimal | None = Field(default=None, ge=0)
    preferred_city: str | None = None
    preferred_region: str | None = None
    status: str | None = None

    @field_validator("category")
    @classmethod
    def category_must_be_supported(cls, value: str | None) -> str | None:
        if value is not None and value not in MATERIAL_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(MATERIAL_CATEGORIES)}")
        return value

    @field_validator("unit")
    @classmethod
    def unit_must_be_supported(cls, value: str | None) -> str | None:
        if value is not None and value not in UNITS:
            raise ValueError(f"unit must be one of: {', '.join(UNITS)}")
        return value

    @field_validator("status")
    @classmethod
    def status_must_be_supported(cls, value: str | None) -> str | None:
        if value is not None and value not in REQUIREMENT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(REQUIREMENT_STATUSES)}")
        return value


class RequirementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    category: str
    description: str | None
    min_quantity: Decimal
    unit: str
    required_grade: str | None
    max_price_per_unit: Decimal | None
    preferred_city: str | None
    preferred_region: str | None
    status: str
    created_at: datetime
    updated_at: datetime
