"""ERP integration boundary models (blueprint Phase 16).

Two deliberately separate concerns:

- ``erp_runs``: per-attempt bookkeeping for preview and confirm operations
  (status/mode/counts/file hash, redacted errors, every failure recorded).
- ``erp_records``: given staging rows (one storage shape for all six entity
  schemas) with idempotency via external ids — the natural key
  ``(adapter_key, entity_type, external_key)`` and the dedup constraint
  ``(adapter_key, entity_type, external_key, content_hash)`` so identical
  repeat imports never duplicate and changed content supersedes history.

Imported rows are staging only: they never write to live marketplace/
trade-chain tables; authorized exports read the live tables and are audited.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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


class ErpRun(Base):
    """Run record for an ERP import preview/confirm attempt (failures too)."""

    __tablename__ = "erp_runs"
    __table_args__ = (
        Index("idx_erp_runs_adapter_started", "adapter_key", "entity_type", "started_at"),
        Index("idx_erp_runs_status_started", "status", "started_at"),
        CheckConstraint(
            "status IN ('previewed','success','failed','skipped')",
            name="ck_erp_runs_status",
        ),
        CheckConstraint("mode IN ('preview','confirm')", name="ck_erp_runs_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    adapter_key: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="preview", server_default="preview")
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


class ErpRecord(Base):
    """One staged ERP record row (idempotent by external id; history kept)."""

    __tablename__ = "erp_records"
    __table_args__ = (
        UniqueConstraint(
            "adapter_key", "entity_type", "external_key", "content_hash",
            name="uq_erp_records_key_hash",
        ),
        Index("idx_erp_records_entity_status", "adapter_key", "entity_type", "status"),
        CheckConstraint(
            "status IN ('active','superseded','quarantined')",
            name="ck_erp_records_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    adapter_key: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    external_key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    row_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    note: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("erp_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )