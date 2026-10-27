import uuid

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_user_read", "user_id", "is_read"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(String(40))
    related_entity_id: Mapped[uuid.UUID | None]
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID | None]
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphSyncRun(Base):
    """Tracks Neo4j projection runs, including failures (blueprint Phase 6)."""

    __tablename__ = "graph_sync_runs"
    __table_args__ = (Index("idx_graph_sync_runs_status", "status", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failed
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    projection_version: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SymbiosisRun(Base):
    """Audit trail for symbiosis discovery runs (blueprint Phase 7)."""

    __tablename__ = "symbiosis_runs"
    __table_args__ = (Index("idx_symbiosis_runs_status", "status", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failed
    error: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    graph_snapshot_id: Mapped[str | None] = mapped_column(String(80))
    discovery_version: Mapped[str] = mapped_column(String(40), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    runtime_ms: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsRun(Base):
    """Run record for marketplace metrics and K-means clustering (Phase 11)."""

    __tablename__ = "analytics_runs"
    __table_args__ = (Index("idx_analytics_runs_kind", "run_kind", "status", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_kind: Mapped[str] = mapped_column(String(40), nullable=False)  # marketplace_metrics | kmeans
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failed
    error: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    feature_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    sampling_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    result_version: Mapped[str] = mapped_column(String(40), nullable=False)
    subjects: Mapped[str] = mapped_column(String(120), nullable=False)
    runtime_ms: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
