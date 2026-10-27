from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import RECOVERY_ROUTES, UNITS


class OfferCreate(BaseModel):
    listing_id: UUID
    requirement_id: UUID
    quantity: Decimal = Field(gt=0)
    price_per_unit: Decimal | None = Field(default=None, ge=0)
    message: str | None = None


class OfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    listing_id: UUID
    requirement_id: UUID
    quantity: Decimal
    price_per_unit: Decimal | None
    message: str | None
    status: str
    created_at: datetime


class OfferDetail(OfferResponse):
    offering_organization: str
    listing_title: str
    requirement_title: str
    transaction_id: UUID | None = None


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    offer_id: UUID
    status: str
    agreed_quantity: Decimal
    agreed_price_per_unit: Decimal | None
    collection_date: date | None
    completed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TransactionDetail(TransactionResponse):
    listing_id: UUID
    listing_title: str
    category: str
    listing_unit: str
    seller_organization: str
    buyer_organization: str
    recovery_record_id: UUID | None = None


class RecoveryRecordCreate(BaseModel):
    recovered_quantity: Decimal = Field(gt=0)
    unit: str
    recovery_route: str
    calculation_notes: str | None = None

    @field_validator("unit")
    @classmethod
    def unit_must_be_supported(cls, value: str) -> str:
        if value not in UNITS:
            raise ValueError(f"unit must be one of: {', '.join(UNITS)}")
        return value

    @field_validator("recovery_route")
    @classmethod
    def route_must_be_supported(cls, value: str) -> str:
        if value not in RECOVERY_ROUTES:
            raise ValueError(f"recovery_route must be one of: {', '.join(RECOVERY_ROUTES)}")
        return value


class RecoveryRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    recovered_quantity: Decimal
    unit: str
    recovery_route: str | None
    estimated_value: Decimal | None
    environmental_estimate: dict
    calculation_notes: str | None
    verification_status: str
    verified_at: datetime | None
    recorded_at: datetime


class RecoveryVerify(BaseModel):
    pass
