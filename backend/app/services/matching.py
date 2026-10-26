"""Deterministic material matching (blueprint Phase 5).

Three layers, all offline and deterministic:

1. Rule baseline (weights from the implementation plan, section 6.3):

     category  40  exact category match required; mismatch rejects the candidate
     quantity  25  meets required quantity = full; below = proportional partial
     quality   20  grade matches = full; unknown grade = partial + warning;
                   mismatched grade = zero
     location  10  preferred city/region match = full; other region = partial
     price      5  within budget = full; unspecified price = zero + warning

   Criteria whose requirement counterpart is missing are excluded and the
   remaining weights are normalized. Missing data never counts as a positive
   match. Rule score is 0-100.

2. Content-based `material_fit` (0-100): taxonomy type match = 100; otherwise
   term-vector cosine between requirement and listing text.

3. `knn_score`: weighted scoring over a normalized feature vector
   [quantity, quality, location, price, material_fit] — a transparent
   feature-based re-rank, NOT a trained model. Weights are documented
   constants; features that do not apply are dropped and the remaining
   weights renormalized.

Hard constraints are enforced before ranking: category mismatch, non-active
listings, non-positive quantities, and over-budget prices exclude a candidate
entirely. Unit normalization: kg and tonne are compared via kg conversion;
litre/unit quantities are never compared against mass.

Compatibility is decision support only — never proof of chemical, legal, or
process safety. Final ordering: knn_score desc, then rule score desc, then
title/id for stable tie-breaking.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaterialRequirement, WasteListing
from app.services.material_intelligence import taxonomy
from app.services.material_intelligence.similarity import tokenize

WEIGHT_CATEGORY = 40
WEIGHT_QUANTITY = 25
WEIGHT_QUALITY = 20
WEIGHT_LOCATION = 10
WEIGHT_PRICE = 5

# Mass units are mutually comparable through kg conversion. Litres and
# countable units are never converted into mass.
MASS_UNIT_TO_KG = {"kg": 1.0, "tonne": 1000.0}

# KNN re-rank weights over the normalized feature vector. Documented, fixed,
# and deterministic — no training data is involved.
KNN_FEATURE_WEIGHTS = {
    "quantity": 0.35,
    "quality": 0.25,
    "location": 0.15,
    "price": 0.05,
    "material_fit": 0.20,
}

ALGORITHM_VERSION = "circular-match-v2"


class MatchCandidate(BaseModel):
    listing_id: UUID
    title: str
    organization_name: str
    category: str
    quantity: str
    unit: str
    city: str
    region: str | None
    price_per_unit: str | None
    currency: str
    grade: str | None
    score: float
    score_breakdown: dict[str, float]
    max_applicable: float
    material_fit: float
    knn_score: float
    algorithm_version: str = ALGORITHM_VERSION
    explanation: str
    warnings: list[str] = Field(default_factory=list)


def _norm(value: str | None) -> str | None:
    return value.strip().lower() if value and value.strip() else None


def _quantity_in_kg(quantity: Decimal, unit: str) -> float | None:
    factor = MASS_UNIT_TO_KG.get(unit)
    return float(quantity) * factor if factor is not None else None


def _material_fit(requirement: MaterialRequirement, listing: WasteListing) -> float:
    """Content-based material similarity, 0-100.

    A taxonomy type match (alias resolution) is exact evidence = 100.
    Otherwise a term-frequency cosine between requirement and listing text.
    """
    requirement_text = " ".join(
        part for part in (requirement.title, requirement.description, requirement.required_grade) if part
    )
    listing_text = " ".join(
        part
        for part in (listing.title, listing.description, listing.material_name, listing.composition, listing.grade)
        if part
    )

    requirement_match = taxonomy.resolve_by_alias(requirement_text)
    listing_match = taxonomy.resolve_by_alias(listing_text)
    if requirement_match and listing_match:
        return 100.0 if requirement_match[0].type_id == listing_match[0].type_id else 0.0

    requirement_tokens = tokenize(requirement_text)
    listing_tokens = tokenize(listing_text)
    if not requirement_tokens or not listing_tokens:
        return 0.0
    requirement_tf = {t: requirement_tokens.count(t) for t in set(requirement_tokens)}
    listing_tf = {t: listing_tokens.count(t) for t in set(listing_tokens)}
    dot = sum(count * listing_tf.get(term, 0.0) for term, count in requirement_tf.items())
    norm_a = sum(count * count for count in requirement_tf.values()) ** 0.5
    norm_b = sum(count * count for count in listing_tf.values()) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return round((dot / (norm_a * norm_b)) * 100, 2)


def score_candidate(requirement: MaterialRequirement, listing: WasteListing) -> MatchCandidate | None:
    """Score one listing against one requirement; None = hard-excluded."""
    if listing.category != requirement.category:
        return None  # incompatible category: rejected, never ranked
    if listing.quantity <= 0:
        return None  # invalid quantity: rejected

    # Hard constraint: a listing priced above the buyer's maximum is excluded
    # entirely (blueprint: exclude hard-constraint violations before ranking).
    if requirement.max_price_per_unit is not None and listing.price_per_unit is not None:
        if listing.price_per_unit > requirement.max_price_per_unit:
            return None

    earned: dict[str, float] = {}
    applicable: dict[str, float] = {}
    reasons: list[str] = []
    warnings: list[str] = []

    earned["category"] = applicable["category"] = WEIGHT_CATEGORY
    reasons.append(f"Category '{listing.category}' matches the requirement")

    # Quantity — normalized to kg when both sides are mass units.
    applicable["quantity"] = WEIGHT_QUANTITY
    listing_kg = _quantity_in_kg(listing.quantity, listing.unit)
    requirement_kg = _quantity_in_kg(requirement.min_quantity, requirement.unit)
    if listing_kg is not None and requirement_kg is not None:
        if listing.unit != requirement.unit:
            reasons.append(
                f"Units normalized for comparison: {listing.quantity} {listing.unit} = "
                f"{listing_kg:g} kg vs required {requirement.min_quantity} {requirement.unit} "
                f"= {requirement_kg:g} kg"
            )
        if listing_kg >= requirement_kg:
            earned["quantity"] = WEIGHT_QUANTITY
            reasons.append(
                f"Available quantity {listing.quantity} {listing.unit} meets the required "
                f"{requirement.min_quantity} {requirement.unit} after unit normalization"
            )
        else:
            ratio = listing_kg / requirement_kg
            earned["quantity"] = round(WEIGHT_QUANTITY * ratio, 2)
            warnings.append(
                f"Insufficient quantity: {listing.quantity} {listing.unit} available but "
                f"{requirement.min_quantity} {requirement.unit} required"
            )
            reasons.append(
                f"Normalized quantity {listing_kg:g} kg is below the required "
                f"{requirement_kg:g} kg (partial credit)"
            )
    elif listing.unit != requirement.unit:
        earned["quantity"] = 0.0
        warnings.append(
            f"Incompatible units: listing is in '{listing.unit}' but the requirement "
            f"is in '{requirement.unit}'; quantity cannot be verified"
        )
        reasons.append("Quantity could not be compared due to incompatible units")
    elif listing.quantity >= requirement.min_quantity:
        earned["quantity"] = WEIGHT_QUANTITY
        reasons.append(
            f"Available quantity {listing.quantity} {listing.unit} meets the required "
            f"{requirement.min_quantity} {requirement.unit}"
        )
    else:
        ratio = float(listing.quantity) / float(requirement.min_quantity)
        earned["quantity"] = round(WEIGHT_QUANTITY * ratio, 2)
        warnings.append(
            f"Insufficient quantity: {listing.quantity} {listing.unit} available but "
            f"{requirement.min_quantity} {requirement.unit} required"
        )
        reasons.append(
            f"Quantity {listing.quantity} {listing.unit} is below the required "
            f"{requirement.min_quantity} {requirement.unit} (partial credit)"
        )

    # Quality / grade
    if requirement.required_grade:
        applicable["quality"] = WEIGHT_QUALITY
        listing_grade = _norm(listing.grade)
        required_grade = _norm(requirement.required_grade)
        if listing_grade is None:
            earned["quality"] = WEIGHT_QUALITY / 2
            warnings.append(
                f"Quality unverified: listing does not state a grade (required: "
                f"'{requirement.required_grade}')"
            )
            reasons.append("Listing grade is unknown; partial quality credit only")
        elif listing_grade == required_grade:
            earned["quality"] = WEIGHT_QUALITY
            reasons.append(f"Grade '{listing.grade}' matches the required grade")
        else:
            earned["quality"] = 0.0
            warnings.append(
                f"Grade mismatch: listing grade '{listing.grade}' does not match "
                f"required '{requirement.required_grade}'"
            )
            reasons.append("Listing grade does not match the required grade")

    # Location
    if requirement.preferred_city or requirement.preferred_region:
        applicable["location"] = WEIGHT_LOCATION
        if requirement.preferred_city and _norm(listing.city) == _norm(requirement.preferred_city):
            earned["location"] = WEIGHT_LOCATION
            reasons.append(f"Located in {listing.city}, matching the preferred city")
        elif requirement.preferred_region and _norm(listing.region) == _norm(
            requirement.preferred_region
        ):
            earned["location"] = WEIGHT_LOCATION
            reasons.append(f"Located in region '{listing.region}', matching the preferred region")
        elif listing.region:
            earned["location"] = WEIGHT_LOCATION / 2
            warnings.append(
                f"Region mismatch: listing is in '{listing.region}' but the preferred "
                f"region is '{requirement.preferred_region}'"
            )
            reasons.append("Different region from the preferred one (partial credit)")
        else:
            earned["location"] = 0.0
            warnings.append("Listing region is unknown; location could not be verified")
            reasons.append("Listing location is incomplete")

    # Price — over-budget was already excluded above as a hard constraint.
    if requirement.max_price_per_unit is not None:
        applicable["price"] = WEIGHT_PRICE
        if listing.price_per_unit is None:
            earned["price"] = 0.0
            warnings.append("Price not specified by the listing; budget fit unknown")
            reasons.append("Listing has no price to compare against the budget")
        else:
            earned["price"] = WEIGHT_PRICE
            reasons.append(
                f"Price {listing.price_per_unit} {listing.currency}/{listing.unit} is within "
                f"the {requirement.max_price_per_unit} budget"
            )

    material_fit = _material_fit(requirement, listing)
    if material_fit >= 100.0:
        reasons.append("Material type confirmed by taxonomy match (content-based fit 100%)")
    else:
        reasons.append(f"Content-based material fit {material_fit:.0f}%")

    total_earned = sum(earned.values())
    max_possible = sum(applicable.values())
    score = round((total_earned / max_possible) * 100, 2)

    # KNN re-rank: weighted scoring over the normalized feature vector.
    features = {
        "quantity": earned["quantity"] / applicable["quantity"],
        "quality": earned["quality"] / applicable["quality"] if "quality" in applicable else None,
        "location": earned["location"] / applicable["location"] if "location" in applicable else None,
        "price": earned["price"] / applicable["price"] if "price" in applicable else None,
        "material_fit": material_fit / 100.0,
    }
    applicable_features = {name: value for name, value in features.items() if value is not None}
    weight_total = sum(KNN_FEATURE_WEIGHTS[name] for name in applicable_features)
    knn_score = round(
        100.0
        * sum(
            KNN_FEATURE_WEIGHTS[name] * value
            for name, value in applicable_features.items()
        )
        / weight_total,
        2,
    )

    explanation = "; ".join(reasons) + "."
    return MatchCandidate(
        listing_id=listing.id,
        title=listing.title,
        organization_name=listing.organization.name,
        category=listing.category,
        quantity=str(listing.quantity),
        unit=listing.unit,
        city=listing.city,
        region=listing.region,
        price_per_unit=str(listing.price_per_unit) if listing.price_per_unit is not None else None,
        currency=listing.currency,
        grade=listing.grade,
        score=score,
        score_breakdown={k: earned[k] for k in sorted(earned)},
        max_applicable=max_possible,
        material_fit=material_fit,
        knn_score=knn_score,
        explanation=explanation,
        warnings=warnings,
    )


def rank_candidates(
    requirement: MaterialRequirement,
    candidates: list[MatchCandidate],
) -> list[MatchCandidate]:
    """KNN re-rank order with stable tie-breaking."""
    return sorted(
        candidates,
        key=lambda c: (-c.knn_score, -c.score, c.title, str(c.listing_id)),
    )


def find_matches(db: Session, requirement: MaterialRequirement) -> list[MatchCandidate]:
    listings = db.scalars(
        select(WasteListing).where(
            WasteListing.status == "active", WasteListing.quantity > 0
        )
    ).all()
    candidates = [
        candidate
        for candidate in (score_candidate(requirement, listing) for listing in listings)
        if candidate is not None
    ]
    return rank_candidates(requirement, candidates)


def _snapshot_breakdown(candidate: MatchCandidate) -> dict:
    return {
        "components": candidate.score_breakdown,
        "max_applicable": candidate.max_applicable,
        "material_fit": candidate.material_fit,
        "knn_score": candidate.knn_score,
        "algorithm_version": candidate.algorithm_version,
        "warnings": candidate.warnings,
    }


def persist_matches(db: Session, requirement: MaterialRequirement, candidates: list[MatchCandidate]) -> int:
    """Upsert match snapshots for the requirement. Returns the number stored."""
    from app.models import Match

    existing = {
        match.listing_id: match
        for match in db.scalars(select(Match).where(Match.requirement_id == requirement.id))
    }
    stored = 0
    for rank, candidate in enumerate(candidates, start=1):
        match = existing.get(candidate.listing_id)
        if match is None:
            match = Match(
                requirement_id=requirement.id,
                listing_id=candidate.listing_id,
                score=candidate.score,
                score_breakdown=_snapshot_breakdown(candidate),
                explanation=candidate.explanation,
                status="suggested",
            )
            db.add(match)
        else:
            match.score = candidate.score
            match.score_breakdown = _snapshot_breakdown(candidate)
            match.explanation = candidate.explanation
            match.generated_at = datetime.now(timezone.utc)
        stored += 1
    db.commit()
    return stored
