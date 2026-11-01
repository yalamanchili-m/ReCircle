"""Pathway optimizer API (blueprint Phase 8)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.services.pathways import evaluation
from app.services.pathways.engine import (
    DEFAULT_PROFILE,
    InfeasibleListing,
    WEIGHT_PROFILES,
    evaluate_pathways,
)

router = APIRouter()


class PathwayEvaluateRequest(BaseModel):
    listing_id: str = Field(min_length=8, max_length=64)
    requirement_id: str | None = Field(default=None, max_length=64)
    destination_region: str | None = Field(default=None, max_length=100)
    profile: str = Field(default=DEFAULT_PROFILE, max_length=40)


@router.post("/pathways/evaluate")
def pathways_evaluate(
    request: PathwayEvaluateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if request.profile not in WEIGHT_PROFILES:
        raise HTTPException(status_code=422, detail=f"Unknown weight profile '{request.profile}'")
    try:
        return evaluate_pathways(
            db,
            listing_id=request.listing_id,
            destination_region=request.destination_region,
            requirement_id=request.requirement_id,
            profile=request.profile,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InfeasibleListing as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/pathways/evaluation")
def pathways_evaluation(current_user: User = Depends(get_current_user)) -> dict:
    return evaluation.evaluate_pathway_optimizer()


@router.get("/pathways/profiles")
def pathways_profiles(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "default": DEFAULT_PROFILE,
        "profiles": WEIGHT_PROFILES,
        "criterion_directions": {
            "environmental_impact": "maximize",
            "distance": "minimize",
            "cost": "minimize",
            "demand": "maximize",
            "feasibility": "maximize",
        },
    }
