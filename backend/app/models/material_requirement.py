import uuid

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import REQUIREMENT_STATUSES, UNITS
from app.db.session import Base

from .organization import Organization


class MaterialRequirement(Base):
    __tablename__ = "material_requirements"
    __table_args__ = (
        CheckConstraint("min_quantity > 0", name="ck_requirements_quantity_positive"),
        CheckConstraint("unit IN ('kg', 'tonne', 'litre', 'unit')", name="ck_requirements_unit"),
        CheckConstraint(
            "status IN ('active', 'paused', 'closed')", name="ck_requirements_status"
        ),
        CheckConstraint(
            "max_price_per_unit IS NULL OR max_price_per_unit >= 0",
            name="ck_requirements_price_nonnegative",
        ),
        Index("idx_requirements_status_category", "status", "category"),
        Index("idx_requirements_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    min_quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    required_grade: Mapped[str | None] = mapped_column(String(100))
    max_price_per_unit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    preferred_city: Mapped[str | None] = mapped_column(String(100))
    preferred_region: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(lazy="joined")

    def __init__(self, **kwargs):
        if "unit" in kwargs and kwargs["unit"] not in UNITS:
            raise ValueError(f"Invalid unit: {kwargs['unit']}")
        if "status" in kwargs and kwargs["status"] not in REQUIREMENT_STATUSES:
            raise ValueError(f"Invalid status: {kwargs['status']}")
        super().__init__(**kwargs)
