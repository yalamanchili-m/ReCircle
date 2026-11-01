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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MATCH_STATUSES
from app.db.session import Base


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_matches_score_range"),
        CheckConstraint(
            "status IN ('suggested', 'viewed', 'interested', 'dismissed', 'converted')",
            name="ck_matches_status",
        ),
        UniqueConstraint("requirement_id", "listing_id", name="uq_matches_requirement_listing"),
        Index("idx_matches_requirement_score", "requirement_id", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_requirements.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("waste_listings.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suggested", server_default="suggested"
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __init__(self, **kwargs):
        if "status" in kwargs and kwargs["status"] not in MATCH_STATUSES:
            raise ValueError(f"Invalid status: {kwargs['status']}")
        super().__init__(**kwargs)
