from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, WasteListing
from app.schemas.listing import ListingResponse
from app.services import ai_enrichment, audit, inventory
from app.services.material_intelligence import evaluate_smoke_set, suggest_material_attributes
from app.services.material_intelligence.engine import ENGINE_VERSION

router = APIRouter()


class EnrichDescriptionRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)


class MaterialSuggestionRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)


class AcceptedSuggestion(BaseModel):
    """A user-reviewed field value accepted into the listing.

    The client sends the (possibly edited) value; the server records that it
    came from an AI suggestion and was human-accepted.
    """

    category: str | None = None
    material_name: str | None = None
    composition: str | None = None
    grade: str | None = None
    possible_applications: list[str] | None = None
    suitable_industries: list[str] | None = None


@router.post("/ai/enrich-description")
def enrich_description(
    payload: EnrichDescriptionRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Optional AI field suggestions. Never blocks listing creation."""
    response = ai_enrichment.enrich_description(payload.description)
    return response.model_dump()


@router.post("/ai/material-suggestions")
def material_suggestions(
    payload: MaterialSuggestionRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reviewable, normalized material suggestions with provenance.

    Advisory only: nothing is stored until a user accepts (possibly edited)
    values via the accept endpoint.
    """
    return suggest_material_attributes(payload.description)


@router.post("/ai/listings/{listing_id}/material-suggestions/accept", response_model=ListingResponse)
def accept_material_suggestions(
    listing_id: UUID,
    payload: AcceptedSuggestion,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListingResponse:
    """Apply user-reviewed AI suggestions to a listing.

    Only explicit fields are written; per-field provenance (ai_inferred +
    model version + acceptance time) is stored in the listing's
    `ai_suggestions` record so inferred values never read as user-provided
    facts.
    """
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)

    accepted_at = datetime.now(timezone.utc).isoformat()
    provenance = dict(listing.ai_suggestions or {})
    updated_fields: list[str] = []

    for field in ("category", "material_name", "composition", "grade"):
        value = getattr(payload, field)
        if value is None:
            continue
        value = value.strip()
        if not value:
            continue
        if field == "category" and value not in _allowed_categories():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported category"
            )
        setattr(listing, field, value)
        updated_fields.append(field)
        provenance[field] = {
            "provenance": "ai_inferred",
            "model_version": ENGINE_VERSION,
            "accepted_at": accepted_at,
            "accepted_by": str(current_user.id),
        }

    for field in ("possible_applications", "suitable_industries"):
        values = getattr(payload, field)
        if values is None:
            continue
        cleaned = [entry.strip() for entry in values if entry.strip()]
        if not cleaned:
            continue
        # These live on the listing's provenance record (WasteListing has no
        # dedicated columns for them).
        provenance[field] = {
            "provenance": "ai_inferred",
            "model_version": ENGINE_VERSION,
            "accepted_at": accepted_at,
            "accepted_by": str(current_user.id),
            "value": cleaned,
        }
        updated_fields.append(field)

    if not updated_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No accepted fields supplied"
        )

    listing.ai_suggestions = provenance
    listing.ai_reviewed = True
    audit.record_audit(
        db,
        actor=current_user,
        action="listing.ai_suggestions_accept",
        entity_type="waste_listing",
        entity_id=listing.id,
        details={"fields": updated_fields, "model_version": ENGINE_VERSION},
    )
    db.commit()
    db.refresh(listing)
    return ListingResponse.model_validate(listing)


def _allowed_categories() -> tuple[str, ...]:
    from app.core.constants import MATERIAL_CATEGORIES

    return tuple(MATERIAL_CATEGORIES)


@router.get("/ai/evaluation")
def ai_evaluation(current_user: User = Depends(get_current_user)) -> dict:
    """Smoke evaluation metrics for the Material Intelligence Engine."""
    return evaluate_smoke_set()
