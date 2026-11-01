"""Regulation-News Aggregator models (blueprint Phase 13).

Blueprint domain model suggested separate ``regulatory_items`` and
``news_items`` tables. This implementation uses a single shared
``regulation_news_items`` table with an ``item_type`` discriminator: both item
families share the same source/deduplication/freshness machinery and every
filtering need (type, jurisdiction, topic) works identically, which makes the
shared table the good existing equivalent the blueprint allows.

Original titles and publisher text are always preserved verbatim; generated
summaries are clearly labeled via ``summary_kind`` and never presented as
legal advice.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RegulationNewsSource(Base):
    """A curated external source (regulator, news, or legal register)."""

    __tablename__ = "regulation_news_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # regulator | news | legal_register
    jurisdiction: Mapped[str] = mapped_column(String(10), nullable=False)
    homepage_url: Mapped[str] = mapped_column(Text, nullable=False)
    feed_url: Mapped[str | None] = mapped_column(Text)
    topics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    terms_note: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_item_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RegulationNewsItem(Base):
    """A source-linked regulation or news item, deduplicated by URL hash."""

    __tablename__ = "regulation_news_items"
    __table_args__ = (
        UniqueConstraint("source_id", "url_hash", name="uq_regnews_source_urlhash"),
        Index("idx_regnews_type_published", "item_type", "published_at"),
        Index("idx_regnews_jurisdiction_published", "jurisdiction", "published_at"),
        Index("idx_regnews_source_fetched", "source_id", "fetched_at"),
        CheckConstraint(
            "item_type IN ('regulation','news')", name="ck_regnews_item_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulation_news_sources.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200))
    jurisdiction: Mapped[str] = mapped_column(String(10), nullable=False)
    topics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    description: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="source_excerpt", server_default="source_excerpt")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RegulationRefreshRun(Base):
    """Run record for refresh attempts, including failures (Phase 13)."""

    __tablename__ = "regulation_refresh_runs"
    __table_args__ = (
        Index("idx_regnews_refresh_runs", "status", "started_at"),
        CheckConstraint("status IN ('success','failed')", name="ck_regnews_refresh_status"),
        CheckConstraint("mode IN ('manual','scheduled')", name="ck_regnews_refresh_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    runtime_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
