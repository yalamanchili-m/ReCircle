"""Regulation-News aggregator API (blueprint Phase 13).

Read/list endpoints are available to every signed-in platform member.
Refresh is admin-gated and audited; external-source failures surface as
per-source statuses instead of crashed requests, and provider outages never
affect inventory/marketplace workflows.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.regulation import (
    RegulationNewsItem,
    RegulationNewsSource,
    RegulationRefreshRun,
)
from app.services import audit
from app.services.regulation import ingest
from app.services.regulation import sources as sources_service

router = APIRouter()

ALLOWED_TYPES = ("regulation", "news")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _item_row(row: RegulationNewsItem, source: RegulationNewsSource) -> dict:
    return {
        "id": str(row.id),
        "source_key": source.key,
        "source_name": source.name,
        "homepage_url": source.homepage_url,
        "item_type": row.item_type,
        "title": row.title,
        "url": row.url,
        "issuer": row.issuer,
        "jurisdiction": row.jurisdiction,
        "topics": list(row.topics or []),
        "summary": row.summary,
        "summary_kind": row.summary_kind,
        "summary_label": ingest.SUMMARY_LABELS.get(row.summary_kind, row.summary_kind),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
    }


@router.get("/regulation/sources")
def regulation_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Curated source registry with freshness stats and setup needs."""
    payload = sources_service.sources_payload(db)
    for source in payload["sources"]:
        row = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == source["key"])
        )
        stale = row is not None and ingest.is_stale(row, now=_now())
        source["stale"] = stale
    db.commit()
    payload["stale_after_days"] = ingest.STALE_SOURCE_DAYS
    return payload


@router.get("/regulation/items")
def regulation_items(
    item_type: str | None = Query(default=None, pattern="^(regulation|news)$"),
    jurisdiction: str | None = Query(default=None, max_length=10),
    topic: str | None = Query(default=None, max_length=60),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Source-linked regulation/news items with filters and stable ordering."""
    conditions = []
    if item_type:
        conditions.append(RegulationNewsItem.item_type == item_type)
    if jurisdiction:
        conditions.append(RegulationNewsItem.jurisdiction == jurisdiction.upper())
    if topic:
        # JSONB equality AND-containment against the stored lowercase topics
        conditions.append(RegulationNewsItem.topics.contains([topic.lower()]))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(
            or_(
                RegulationNewsItem.title.ilike(like),
                RegulationNewsItem.summary.ilike(like),
                RegulationNewsItem.description.ilike(like),
            )
        )

    base = select(RegulationNewsItem).join(
        RegulationNewsSource, RegulationNewsItem.source_id == RegulationNewsSource.id
    )
    query = (
        base.where(*conditions)
        .order_by(
            RegulationNewsItem.published_at.desc().nullslast(),
            RegulationNewsItem.fetched_at.desc(),
            RegulationNewsItem.id,
        )
        .limit(limit)
        .offset(offset)
    )
    rows = db.scalars(query).all()
    source_map = {
        source.id: source
        for source in db.scalars(select(RegulationNewsSource)).all()
    }
    total = db.scalar(
        select(func.count())
        .select_from(RegulationNewsItem)
        .join(RegulationNewsSource, RegulationNewsItem.source_id == RegulationNewsSource.id)
        .where(*conditions)
    )
    db.commit()
    return {
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "summary_labels": ingest.SUMMARY_LABELS,
        "disclaimers": ingest.DISCLAIMERS,
        "items": [_item_row(item, source_map[item.source_id]) for item in rows],
    }


@router.get("/regulation/items/{item_id}")
def regulation_item_detail(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Item detail: original description preserved next to its summary."""
    row = db.get(RegulationNewsItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Regulation/news item not found")
    source = db.get(RegulationNewsSource, row.source_id)
    db.commit()
    assert source is not None
    payload = _item_row(row, source)
    payload["description"] = row.description
    payload["disclaimers"] = ingest.DISCLAIMERS
    return payload


@router.post("/regulation/refresh")
def regulation_refresh(
    source_key: str | None = Query(default=None, max_length=60),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Manual refresh (admin). Per-source failures are reported, not raised."""
    try:
        payload = ingest.refresh(db, current_user, source_key)
    except ValueError as error:
        db.commit()  # keep the failed run record for auditing
        raise HTTPException(status_code=422, detail=str(error))
    audit.record_audit(
        db,
        actor=current_user,
        action="regulation.refresh",
        entity_type="regulation_source",
        details={
            "source_key": source_key,
            "status": payload["status"],
            "totals": payload["totals"],
        },
    )
    db.commit()
    return payload


@router.get("/regulation/refresh-runs")
def regulation_refresh_runs(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Recent refresh-run history (admin), including failed attempts."""
    rows = db.scalars(
        select(RegulationRefreshRun)
        .order_by(RegulationRefreshRun.started_at.desc())
        .limit(limit)
    ).all()
    db.commit()
    return {
        "runs": [
            {
                "id": str(run.id),
                "status": run.status,
                "error": run.error,
                "mode": run.mode,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "runtime_ms": run.runtime_ms,
                "stats": run.stats,
            }
            for run in rows
        ]
    }
