import uuid

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

from .organization import Organization
from .user import User


class MaterialPassport(Base):
    """Versioned Material Passport bound to a waste listing.

    Each edit produces a new immutable version row; exactly one row per
    listing is `active`, previous versions become `superseded`. Attribute
    provenance (user_provided / source_derived / ai_inferred / unverified)
    travels with every attribute so inferred values are never presented as
    verified facts.
    """

    __tablename__ = "material_passports"
    __table_args__ = (
        UniqueConstraint("listing_id", "version", name="uq_passports_listing_version"),
        CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_passports_status"
        ),
        CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed')",
            name="ck_passports_review_status",
        ),
        CheckConstraint("version >= 1", name="ck_passports_version_positive"),
        Index("idx_passports_listing_status", "listing_id", "status"),
        Index("idx_passports_organization", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("waste_listings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )

    # Structured content. `attributes` maps field name ->
    # {value, provenance, confidence (optional)}. Unknown values are null,
    # never zero.
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    possible_applications: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    suitable_industries: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    candidate_pathways: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unreviewed", server_default="unreviewed"
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    listing: Mapped["WasteListing"] = relationship(lazy="joined")  # noqa: F821
    organization: Mapped[Organization] = relationship(lazy="joined")
    reviewer: Mapped[User | None] = relationship(
        lazy="joined", foreign_keys=[reviewed_by]
    )
    author: Mapped[User | None] = relationship(
        lazy="joined", foreign_keys=[created_by]
    )
