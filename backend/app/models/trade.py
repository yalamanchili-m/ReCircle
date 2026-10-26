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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_offers_quantity_positive"),
        CheckConstraint(
            "price_per_unit IS NULL OR price_per_unit >= 0", name="ck_offers_price_nonnegative"
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'withdrawn')", name="ck_offers_status"
        ),
        Index("idx_offers_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("matches.id", ondelete="SET NULL")
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("waste_listings.id"), nullable=False)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_requirements.id"), nullable=False
    )
    offered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    price_per_unit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("agreed_quantity > 0", name="ck_transactions_quantity_positive"),
        CheckConstraint(
            "status IN ('agreed', 'collection_scheduled', 'in_transit', 'delivered', "
            "'completed', 'cancelled')",
            name="ck_transactions_status",
        ),
        Index("idx_transactions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="agreed", server_default="agreed"
    )
    agreed_quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    agreed_price_per_unit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    collection_date: Mapped[datetime | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RecoveryRecord(Base):
    __tablename__ = "recovery_records"
    __table_args__ = (CheckConstraint("recovered_quantity >= 0", name="ck_recovery_quantity"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id"), nullable=False, unique=True
    )
    recovered_quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    recovery_route: Mapped[str | None] = mapped_column(String(80))
    estimated_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    environmental_estimate: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    calculation_notes: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
