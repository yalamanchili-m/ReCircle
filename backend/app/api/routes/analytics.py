"""Marketplace metrics + K-means clustering API (blueprint Phase 11)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.services import analytics, audit

router = APIRouter()


@router.get("/analytics/marketplace")
def marketplace_metrics(
    period_from: date | None = Query(default=None),
    period_to: date | None = Query(default=None),
    category: str | None = Query(default=None, max_length=40),
    industry: str | None = Query(default=None, max_length=80),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Database-backed marketplace metrics with documented gating."""
    try:
        payload = analytics.run_marketplace_metrics(
            db,
            current_user,
            period_from=period_from.isoformat() if period_from else None,
            period_to=period_to.isoformat() if period_to else None,
            category=category,
            industry=industry,
        )
    except ValueError as error:
        db.commit()  # keep the failed run record; it documents the failure
        raise HTTPException(status_code=422, detail=str(error))
    db.commit()
    return payload


@router.get("/analytics/marketplace/export")
def marketplace_export(
    period_from: date | None = Query(default=None),
    period_to: date | None = Query(default=None),
    category: str | None = Query(default=None, max_length=40),
    industry: str | None = Query(default=None, max_length=80),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """CSV export of aggregates only — no private organization data."""
    try:
        payload = analytics.run_marketplace_metrics(
            db,
            current_user,
            period_from=period_from.isoformat() if period_from else None,
            period_to=period_to.isoformat() if period_to else None,
            category=category,
            industry=industry,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    db.commit()
    audit.record_audit(
        db,
        actor=current_user,
        action="analytics.export",
        entity_type="marketplace_metrics",
        details={
            "category": category,
            "industry": industry,
            "period_from": period_from.isoformat() if period_from else None,
            "period_to": period_to.isoformat() if period_to else None,
        },
    )
    db.commit()
    csv_body = analytics.marketplace_metrics_csv(payload)
    return PlainTextResponse(
        content=csv_body,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="marketplace_metrics.csv"'
        },
    )


@router.post("/analytics/kmeans")
def kmeans_endpoint(
    subject: str = Query(...),
    k: int | None = Query(default=None, ge=2, le=6),
    category: str | None = Query(default=None, max_length=40),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Deterministic exploratory clustering; every run recorded."""
    try:
        payload = analytics.run_kmeans(db, current_user, subject, k, category)
    except ValueError as error:
        db.commit()  # keep the failed run record; it documents the failure
        raise HTTPException(status_code=422, detail=str(error))
    db.commit()
    return payload


@router.post("/analytics/recompute")
def analytics_recompute(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Admin convenience: re-run metrics + both clustering subjects."""
    results: dict = {}
    for subject in ("listings", "requirements"):
        results[subject] = analytics.run_kmeans(
            db, current_user, subject, None, None
        )
    results["marketplace_metrics"] = analytics.run_marketplace_metrics(db, current_user)
    db.commit()
    audit.record_audit(
        db,
        actor=current_user,
        action="analytics.recompute",
        entity_type="analytics",
        details={"subjects": ["listings", "requirements", "marketplace_metrics"]},
    )
    db.commit()
    return results
