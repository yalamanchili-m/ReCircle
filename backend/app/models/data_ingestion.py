"""External data ingestion models (blueprint Phase 15).

Create a source registry, keep raw staged files separate from
normalized records, record run bookkeeping, and — for EPA WARM — land
validated factor rows that the carbon service can consume in place of the
curated approximation catalog.

Tables are deliberately separated:
- ``external_data_sources``: the curated source registry (description,
  jurisdiction, terms/licence notes, URL, version, update cadence).
- ``ingestion_runs``: per-import bookkeeping (accepted/rejected/quarantined
  counts, warnings, hashes, errors) for repeatable, auditable imports.
- ``ingestion_raw_files``: raw staged file snapshots (SHA-256, stored path);
  raw payloads never live inside normalized rows.
- ``ingestion_records``: normalized rows from tabular material-flow sources
  (status active/superseded/quarantined with close to zero substitutions —
  missing values are stored as JSON null plus a note, never as zeros).
- ``ingestion_warm_factors``: validated WARM factor rows; only rows flagged
  ``is_active`` form the active catalog consumed by ``app.services.carbon``
  (previous versions stay persisted as history, mirroring impact estimates).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ExternalDataSource(Base):
    """One curated external-data source (blueprint Phase 15 registry)."""

    __tablename__ = "external_data_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    family: Mapped[str] = mapped_column(String(40), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    homepage_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    terms_note: Mapped[str] = mapped_column(Text, nullable=False)
    access_note: Mapped[str | None] = mapped_column(Text)
    expected_format: Mapped[str] = mapped_column(String(40), nullable=False)
    adapter: Mapped[str | None] = mapped_column(String(40))
    adapter_status: Mapped[str] = mapped_column(String(30), nullable=False)
    declared_version: Mapped[str | None] = mapped_column(String(255))
    update_cadence: Mapped[str] = mapped_column(String(60), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    latest_file_hash: Mapped[str | None] = mapped_column(String(64))
    latest_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionRun(Base):
    """Run record for a staged-file import attempt, including failures."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("idx_ing_runs_source_started", "source_id", "started_at"),
        Index("idx_ing_runs_status_started", "status", "started_at"),
        CheckConstraint(
            "status IN ('success','failed','skipped')", name="ck_ing_runs_status"
        ),
        CheckConstraint("mode IN ('manual','scheduled')", name="ck_ing_runs_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("external_data_sources.id", ondelete="SET NULL")
    )
    source_key: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    error: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    file_hash: Mapped[str | None] = mapped_column(String(64))
    runtime_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawIngestionFile(Base):
    """Raw staged file snapshot, kept separate from normalized records."""

    __tablename__ = "ingestion_raw_files"
    __table_args__ = (
        UniqueConstraint("source_id", "file_hash", name="uq_ing_raw_source_hash"),
        Index("idx_ing_raw_source_first", "source_id", "first_imported_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("external_data_sources.id", ondelete="CASCADE"), nullable=False
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_name: Mapped[str] = mapped_column(String(260), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    declared_version: Mapped[str | None] = mapped_column(String(255))
    import_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalDataRecord(Base):
    """One normalized material-flow record (raw row kept adjacent in JSONB).

    ``status`` lifecycle: ``active`` contributes to reads; a later import
    superseding the same natural key demotes the older row to ``superseded``
    (history preserved, no silent overwrite); semantic failures are stored
    as ``quarantined`` with an explicit reason. Missing values are JSON
    null + note — never blind zero-fill.
    """

    __tablename__ = "ingestion_records"
    __table_args__ = (
        UniqueConstraint("source_id", "natural_key", "content_hash", name="uq_ing_records_key_hash"),
        Index("idx_ing_records_source_status", "source_id", "status"),
        CheckConstraint(
            "status IN ('active','superseded','quarantined')",
            name="ck_ing_records_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("external_data_sources.id", ondelete="CASCADE"), nullable=False
    )
    natural_key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    row_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    note: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalWarmFactor(Base):
    """One validated WARM factor row; ``is_active`` rows form the catalog.

    Mirrors the impact-estimate lifecycle: activating a newly ingested set
    deactivates the previous one in place so exactly one set is active (a
    partial unique index enforces one active row per (category, pathway)),
    and history remains queryable for traceability.
    """

    __tablename__ = "ingestion_warm_factors"
    __table_args__ = (
        Index(
            "uq_ing_warm_active",
            "category",
            "pathway",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("idx_ing_warm_version_cat", "catalog_version", "category", "pathway"),
        CheckConstraint(
            "uncertainty_ratio >= 0 AND uncertainty_ratio <= 1",
            name="ck_ing_warm_uncertainty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    catalog_version: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_source: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    pathway: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    uncertainty_ratio: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
