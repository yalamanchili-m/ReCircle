"""Symbiosis discovery API (blueprint Phase 7)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.services.symbiosis import evaluation
from app.services.symbiosis.engine import discover_opportunities

router = APIRouter()


@router.get("/symbiosis/opportunities")
def symbiosis_opportunities(
    category: str | None = Query(default=None, max_length=80),
    region: str | None = Query(default=None, max_length=100),
    max_depth: int = Query(default=4, ge=1, le=6),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return discover_opportunities(
        db,
        category=category,
        region=region,
        max_depth=max_depth,
        min_confidence=min_confidence,
        limit=limit,
    )


@router.get("/symbiosis/evaluation")
def symbiosis_evaluation(
    current_user: User = Depends(get_current_user),
) -> dict:
    return evaluation.evaluate_symbiosis()
