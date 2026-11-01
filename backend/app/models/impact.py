import uuid

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ImpactEstimate(Base):
    """Factor-based environmental estimate for one recovery record (Phase 9/12).

    One estimate row is persisted per recovery record per (re)calculation;
    only the row flagged `is_current` contributes to ESG aggregation, so
    updated factors never double-count. Unsupported combinations are stored
    with null values plus an explicit reason — never as fabricated zeros.
    """

    __tablename__ = "impact_estimates"
    __table_args__ = (
        Index(
            "uq_impact_estimates_current",
            "recovery_record_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("idx_impact_estimates_recovery", "recovery_record_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_records.id", ondelete="CASCADE"), nullable=False
    )
    recovery_route: Mapped[str | None] = mapped_column(String(80))
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unsupported_reason: Mapped[str | None] = mapped_column(Text)

    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(20))
    quantity_tonnes: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    avoided_co2e_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    landfill_diverted_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))

    method: Mapped[str] = mapped_column(String(60), nullable=False)
    factor_catalog_version: Mapped[str] = mapped_column(String(60), nullable=False)
    factor_source: Mapped[str] = mapped_column(String(180), nullable=False)
    baseline_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
