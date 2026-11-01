import uuid

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import LISTING_STATUSES, UNITS
from app.db.session import Base

from .organization import Organization
from .user import User


class WasteListing(Base):
    __tablename__ = "waste_listings"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_listings_quantity_positive"),
        CheckConstraint(
            "unit IN ('kg', 'tonne', 'litre', 'unit')", name="ck_listings_unit"
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'matched', 'archived')", name="ck_listings_status"
        ),
        CheckConstraint(
            "price_per_unit IS NULL OR price_per_unit >= 0", name="ck_listings_price_nonnegative"
        ),
        Index("idx_listings_status_category", "status", "category"),
        Index("idx_listings_organization", "organization_id"),
        Index("idx_listings_location", "city", "region"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    material_name: Mapped[str | None] = mapped_column(String(120))
    composition: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str | None] = mapped_column(String(100))
    condition: Mapped[str | None] = mapped_column(String(80))
    contamination_notes: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    price_per_unit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR", server_default="INR")
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="India", server_default="India")
    available_from: Mapped[datetime | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    ai_suggestions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    ai_reviewed: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(lazy="joined")
    creator: Mapped[User | None] = relationship(lazy="joined")

    def __init__(self, **kwargs):
        if "unit" in kwargs and kwargs["unit"] not in UNITS:
            raise ValueError(f"Invalid unit: {kwargs['unit']}")
        if "status" in kwargs and kwargs["status"] not in LISTING_STATUSES:
            raise ValueError(f"Invalid status: {kwargs['status']}")
        super().__init__(**kwargs)
