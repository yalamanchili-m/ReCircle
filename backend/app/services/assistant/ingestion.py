"""Knowledge ingestion & chunk synchronization for the assistant.

`sync_knowledge(db)` materializes the platform-scope corpus idempotently:
- trusted curated method documents (stable `chunk_key` per window),
  re-hashed on content change and deactivated when windows vanish;
- public regulation/news items from Phase 13, chunked from title +
  labeled summary + description only for items that are actually readable
  by any platform member (they are platform-scope by design).

Org-private records are deliberately NOT persisted here: they are retrieved
live from PostgreSQL with org filters applied before scoring
(`engine.py`), which is the strongest possible tenant-permission policy.
"""

import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assistant import KnowledgeChunk
from app.models.regulation import RegulationNewsItem
from app.services.assistant.documents import (
    DOCUMENTS_VERSION,
    chunk_text,
    content_hash_of,
    method_documents,
)

INGESTION_VERSION = "assistant-ingest-v1"

_MAX_REGULATION_ITEMS = 200
_MAX_CHUNKS_PER_ITEM = 3

_SUMMARY_LABEL_MAP = {
    "source_excerpt": "Source excerpt (automated)",
    "ai_generated": "AI-generated summary (informational, not legal advice)",
}

_WHITESPACE = re.compile(r"\s+")


def _clean(text: str | None, limit: int = 2000) -> str:
    return _WHITESPACE.sub(" ", (text or "")).strip()[:limit]


def _regulation_chunk_text(item: RegulationNewsItem, title: str) -> str:
    label = _SUMMARY_LABEL_MAP.get(item.summary_kind, _SUMMARY_LABEL_MAP["source_excerpt"])
    return title + "\n\n" + label + ". " + _clean(item.summary or item.description)


def _document_chunks() -> dict[str, dict]:
    """Build expected chunk rows keyed by stable chunk_key."""
    expected: dict[str, dict] = {}
    for doc_index, doc in enumerate(method_documents()):
        windows = chunk_text(doc["content"])
        for ordinal, window in enumerate(windows):
            key = f"doc:{document_slug(doc['title'])}:{ordinal}"
            content = (
                doc["title"]
                + (f" (part {ordinal + 1}/{len(windows)})" if len(windows) > 1 else "")
                + "\n\n"
                + window
            )
            expected[key] = {
                "key": key,
                "source_type": "method_document",
                "source_ref_id": f"method_docs:{doc_index}",
                "title": doc["title"],
                "content": content,
                "content_hash": content_hash_of(content),
                "idx_ordinal": ordinal,
                "is_trusted": True,
                "is_active": True,
            }
    return expected


def _regulation_chunks(db: Session) -> dict[str, dict]:
    ids = db.scalars(
        select(RegulationNewsItem.id)
        .order_by(RegulationNewsItem.published_at.desc().nullslast())
        .limit(_MAX_REGULATION_ITEMS)
    ).all()
    if not ids:
        return {}
    items = {
        item.id: item
        for item in db.scalars(
            select(RegulationNewsItem).where(
                RegulationNewsItem.id.in_([uuid.UUID(str(i)) for i in ids])
            )
        )
    }
    expected: dict[str, dict] = {}
    for item in items.values():
        title = _clean(item.title, limit=300)
        windows = chunk_text(_regulation_chunk_text(item, title))[: _MAX_CHUNKS_PER_ITEM]
        for ordinal, window in enumerate(windows):
            key = f"reg:{item.id}:{ordinal}"
            content = title + ("" if ordinal == 0 else f" (cont. {ordinal + 1})") + "\n\n" + window
            expected[key] = {
                "key": key,
                "source_type": "regulation_item",
                "source_ref_id": str(item.id),
                "title": title,
                "content": content,
                "content_hash": content_hash_of(content),
                "idx_ordinal": ordinal,
                "is_trusted": False,
                "is_active": True,
            }
    return expected


def document_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16] if not slug else slug[:60]


def sync_knowledge(db: Session) -> dict:
    """Idempotently materialize expected chunks; deactivate stale rows.

    Content changes update the existing row in place (stable `chunk_key`),
    so re-runs never duplicate and old citation ids stay addressable (URLs
    of history entries/history entries remain stable as ids only).
    """
    expected: dict[str, dict] = _document_chunks()
    expected.update(_regulation_chunks(db))

    existing = {
        row.chunk_key: row
        for row in db.scalars(select(KnowledgeChunk))
    }
    inserted, updated = [], []
    for key, payload in expected.items():
        row = existing.get(key)
        if row is None:
            db.add(
                KnowledgeChunk(
                    chunk_key=payload["key"],
                    source_type=payload["source_type"],
                    source_ref_id=payload["source_ref_id"],
                    title=payload["title"],
                    content=payload["content"],
                    content_hash=payload["content_hash"],
                    access_scope="platform",
                    idx_ordinal=payload["idx_ordinal"],
                    is_trusted=payload["is_trusted"],
                    is_active=True,
                )
            )
            inserted.append(key)
        elif row.content_hash != payload["content_hash"] or not row.is_active:
            row.title = payload["title"]
            row.content = payload["content"]
            row.content_hash = payload["content_hash"]
            row.is_trusted = payload["is_trusted"]
            row.is_active = True
            row.is_active = True
            updated.append(key)
    # Deactivate rows that are no longer produced (document removed, item gone).
    deactivated = []
    for key, row in existing.items():
        if key not in expected and row.is_active:
            row.is_active = False
            deactivated.append(key)
    db.flush()
    return {
        "ingestion_version": INGESTION_VERSION,
        "documents_version": DOCUMENTS_VERSION,
        "inserted": len(inserted),
        "updated": len(updated),
        "deactivated": len(deactivated),
        "active_chunks": len(expected),
    }
