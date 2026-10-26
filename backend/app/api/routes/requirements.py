from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Match, User, WasteListing
from app.schemas.requirement import (
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
)
from app.services import audit, matching, matching_evaluation, requirements

router = APIRouter()


class MatchRunResponse(BaseModel):
    requirement_id: UUID
    persisted: bool
    candidate_count: int
    results: list[matching.MatchCandidate]


class StoredMatchResponse(BaseModel):
    id: UUID
    requirement_id: UUID
    listing_id: UUID
    listing_title: str
    organization_name: str
    score: float
    score_breakdown: dict
    explanation: str
    status: str
    generated_at: object


@router.get("/requirements", response_model=list[RequirementResponse])
def list_requirements(
    requirement_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RequirementResponse]:
    items, _total = requirements.list_requirements(
        db, user=current_user, requirement_status=requirement_status, page=page, page_size=page_size
    )
    return [RequirementResponse.model_validate(item) for item in items]


@router.post("/requirements", response_model=RequirementResponse, status_code=status.HTTP_201_CREATED)
def create_requirement(
    payload: RequirementCreate,
    current_user: User = Depends(require_roles("buyer", "admin")),
    db: Session = Depends(get_db),
) -> RequirementResponse:
    requirement = requirements.create_requirement(db, payload, current_user)
    audit.record_audit(
        db,
        actor=current_user,
        action="requirement.create",
        entity_type="material_requirement",
        entity_id=requirement.id,
        details={"title": requirement.title},
    )
    db.commit()
    return RequirementResponse.model_validate(requirement)


@router.get("/requirements/{requirement_id}", response_model=RequirementResponse)
def get_requirement(
    requirement_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RequirementResponse:
    requirement = requirements.get_requirement_or_404(db, requirement_id)
    requirements.assert_can_manage(requirement, current_user)
    return RequirementResponse.model_validate(requirement)


@router.patch("/requirements/{requirement_id}", response_model=RequirementResponse)
def update_requirement(
    requirement_id: UUID,
    payload: RequirementUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RequirementResponse:
    requirement = requirements.get_requirement_or_404(db, requirement_id)
    requirements.assert_can_manage(requirement, current_user)
    requirement = requirements.update_requirement(db, requirement, payload)
    audit.record_audit(
        db,
        actor=current_user,
        action="requirement.update",
        entity_type="material_requirement",
        entity_id=requirement.id,
        details={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    db.commit()
    return RequirementResponse.model_validate(requirement)


@router.post("/requirements/{requirement_id}/matches", response_model=MatchRunResponse)
def run_matching(
    requirement_id: UUID,
    persist: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MatchRunResponse:
    requirement = requirements.get_requirement_or_404(db, requirement_id)
    requirements.assert_can_manage(requirement, current_user)

    candidates = matching.find_matches(db, requirement)
    persisted = False
    if persist:
        matching.persist_matches(db, requirement, candidates)
        audit.record_audit(
            db,
            actor=current_user,
            action="requirement.match_run",
            entity_type="material_requirement",
            entity_id=requirement.id,
            details={"candidate_count": len(candidates)},
        )
        db.commit()
        persisted = True
    return MatchRunResponse(
        requirement_id=requirement.id,
        persisted=persisted,
        candidate_count=len(candidates),
        results=candidates,
    )


@router.get("/matching/evaluation")
def matching_evaluation_endpoint(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Scenario evaluation for the matching engine (synthetic set, disclaimer)."""
    return matching_evaluation.evaluate_matching()


@router.get("/requirements/{requirement_id}/matches", response_model=list[StoredMatchResponse])
def list_stored_matches(
    requirement_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StoredMatchResponse]:
    requirement = requirements.get_requirement_or_404(db, requirement_id)
    requirements.assert_can_manage(requirement, current_user)

    rows = db.execute(
        select(Match, WasteListing)
        .join(WasteListing, Match.listing_id == WasteListing.id)
        .where(Match.requirement_id == requirement.id)
        .order_by(Match.score.desc(), WasteListing.title)
    ).all()
    return [
        StoredMatchResponse(
            id=match.id,
            requirement_id=match.requirement_id,
            listing_id=listing.id,
            listing_title=listing.title,
            organization_name=listing.organization.name,
            score=float(match.score),
            score_breakdown=match.score_breakdown,
            explanation=match.explanation,
            status=match.status,
            generated_at=match.generated_at,
        )
        for match, listing in rows
    ]
