from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import (
    ImpactEstimate,
    MaterialRequirement,
    Match,
    Offer,
    Transaction,
    User,
    WasteListing,
)
from app.services import explainability, trade
from app.services.pathways import templates
from app.services.pathways.engine import InfeasibleListing, evaluate_pathways

router = APIRouter()


@router.get("/explain/status")
def explain_status(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Model governance: deployed models, SHAP/LIME support, limitations."""
    return explainability.explain_subject_status()


@router.get("/explain/match/{match_id}")
def explain_match(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """'Why this match?' — native rule contributions for a stored snapshot."""
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")

    requirement = db.get(MaterialRequirement, match.requirement_id)
    listing = db.get(WasteListing, match.listing_id)
    is_platform_admin = current_user.role == "admin" and current_user.organization_id is None
    if not is_platform_admin:
        org_id = current_user.organization_id
        if org_id is None or org_id not in (requirement.organization_id, listing.organization_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only participants may inspect this match explanation",
            )
    explanation = explainability.explain_match(
        {
            "score_breakdown": match.score_breakdown,
            "explanation": match.explanation,
        }
    )
    explanation["inputs"] = {
        "match_id": str(match.id),
        "requirement_id": str(match.requirement_id),
        "listing_id": str(match.listing_id),
        "title": listing.title,
        "score": float(match.score),
        "assessment_text": match.explanation,
    }
    return explanation


@router.get("/explain/impact/{recovery_record_id}")
def explain_impact(
    recovery_record_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """'What influenced this estimate?' — factor arithmetic replay."""
    recovery = trade.get_recovery_for_user(db, recovery_record_id, current_user)
    estimate = db.scalars(
        select(ImpactEstimate)
        .where(
            ImpactEstimate.recovery_record_id == recovery.id,
            ImpactEstimate.is_current.is_(True),
        )
        .order_by(ImpactEstimate.created_at.desc(), ImpactEstimate.id)
    ).first()
    if estimate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No impact estimate stored for this recovery record",
        )
    row = db.execute(
        select(WasteListing.category)
        .join(Offer, Offer.listing_id == WasteListing.id)
        .join(Transaction, Transaction.offer_id == Offer.id)
        .where(Transaction.id == recovery.transaction_id)
    ).first()
    category = row[0] if row else None
    explanation = explainability.explain_impact(estimate, category)
    explanation["inputs"].update(
        {
            "recovery_record_id": str(recovery.id),
            "estimated_value": (
                float(estimate.avoided_co2e_kg)
                if estimate.avoided_co2e_kg is not None
                else None
            ),
            "diverted_kg": (
                float(estimate.landfill_diverted_kg)
                if estimate.landfill_diverted_kg is not None
                else None
            ),
        }
    )
    return explanation


@router.get("/explain/pathway")
def explain_pathway(
    listing_id: UUID,
    pathway: str | None = None,
    profile: str = "default",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """'Why this pathway?' — native WSM contributions for one candidate.

    The deterministic evaluator is re-run with the exact same inputs and
    versions, so the explanation corresponds to the exact prediction inputs.
    """
    listing = db.get(WasteListing, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    is_platform_admin = current_user.role == "admin" and current_user.organization_id is None
    if not is_platform_admin and current_user.organization_id != listing.organization_id:
        if listing.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner organization may inspect non-active listing pathways",
            )
    try:
        result = evaluate_pathways(db, listing_id=listing.id, profile=profile)
    except InfeasibleListing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No feasible pathway for this listing"
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))

    if pathway is None:
        candidate = (result.get("ranked") or [None])[0]
    else:
        if pathway not in templates.all_pathway_ids():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unknown pathway '{pathway}'; supported: "
                    f"{', '.join(templates.all_pathway_ids())}"
                ),
            )
        candidate = next((c for c in result["ranked"] if c["pathway"] == pathway), None)

    if candidate is None:
        rejected = next(
            (r for r in result["rejected"] if r["pathway"] == (pathway or "")),
            None,
        )
        payload = explainability.build_explanation(
            subject_type="pathway",
            subject_version=f"{result['versions']['optimizer']} | "
            f"{templates.PATHWAY_TEMPLATES_VERSION}",
            inputs={
                "listing_id": str(listing.id),
                "pathway": pathway or "top",
                "profile": profile,
                "raw_values": None,
                "normalized_values": None,
                "criterion_weights": None,
            },
            contributions=[
                {
                    "feature": "feasibility_gate",
                    "value": 0.0,
                    "unit": "boolean",
                    "direction": "neutral",
                    "detail": rejected["reason"]
                    if rejected
                    else "Not feasible for this listing; excluded before ranking",
                }
            ],
            caveats=explainability.PATHWAY_CAVEATS
            + ["This pathway was excluded BEFORE ranking by the hard feasibility rules."],
            data_coverage={"rejected": True, "reason": (rejected or {}).get("reason")},
        )
        return payload

    return explainability.explain_pathway(candidate, profile)
