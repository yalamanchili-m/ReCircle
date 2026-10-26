from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import LISTING_STATUSES, MATERIAL_CATEGORIES, UNITS

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ListingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1)
    category: str
    material_name: str | None = Field(default=None, max_length=120)
    composition: str | None = None
    grade: str | None = Field(default=None, max_length=100)
    condition: str | None = Field(default=None, max_length=80)
    contamination_notes: str | None = None
    quantity: Decimal = Field(gt=0)
    unit: str
    price_per_unit: Decimal | None = Field(default=None, ge=0)
    city: str = Field(min_length=1, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    available_from: date | None = None

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


class ListingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, min_length=1)
    category: str | None = None
    material_name: str | None = None
    composition: str | None = None
    grade: str | None = None
    condition: str | None = None
    contamination_notes: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None
    price_per_unit: Decimal | None = Field(default=None, ge=0)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = None
    available_from: date | None = None

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


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    category: str
    material_name: str | None
    composition: str | None
    grade: str | None
    condition: str | None
    contamination_notes: str | None
    quantity: Decimal
    unit: str
    price_per_unit: Decimal | None
    currency: str
    city: str
    region: str | None
    country: str
    available_from: date | None
    status: str
    ai_suggestions: dict
    ai_reviewed: bool
    created_at: datetime
    updated_at: datetime


class ListingPage(BaseModel):
    items: list[ListingResponse]
    total: int
    page: int
    page_size: int
