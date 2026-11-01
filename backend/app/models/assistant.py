"""AI Sustainability Assistant models (blueprint Phase 14, RAG).

Two tables:
- ``assistant_knowledge_chunks``: preprocessed, chunked platform-scope
  knowledge (curated methodology documents + public regulation/news items).
  Org-private records are retrieved live from PostgreSQL with org filters
  applied BEFORE scoring, so tenant permissions are enforced at retrieval
  time, not only after generation.
- ``assistant_runs``: one row per question with mode, answer, citations,
  retrieval stats, and versions - answers stay auditable and reproducible.
"""

import uuid

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class KnowledgeChunk(Base):
    """Platform-scope knowledge chunk with provenance and hashing."""

    __tablename__ = "assistant_knowledge_chunks"
    __table_args__ = (
        Index("idx_assistant_chunks_active_source", "is_active", "source_type"),
        CheckConstraint(
            "source_type IN ('method_document','platform_note','regulation_item')",
            name="ck_assistant_chunks_source_type",
        ),
        CheckConstraint(
            "access_scope IN ('platform')",
            name="ck_assistant_chunks_access_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chunk_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    access_scope: Mapped[str] = mapped_column(String(30), nullable=False, default="platform", server_default="platform")
    idx_ordinal: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    is_trusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssistantRun(Base):
    """Audit record for one sustainability-assistant question."""

    __tablename__ = "assistant_runs"
    __table_args__ = (
        Index("idx_assistant_runs_user", "user_id", "created_at"),
        CheckConstraint(
            "mode IN ('generated','retrieve_only','abstained','refused')",
            name="ck_assistant_runs_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    retrieval_stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    retrieval_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120))
    runtime_ms: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
