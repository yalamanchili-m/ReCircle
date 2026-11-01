"""Circular Path Optimizer — Weighted Sum Model (MCDM), blueprint Phase 8.

Deterministic ranking of the four pathway types for a listing. Hard
feasibility is enforced BEFORE scoring; scores never override safety or
regulatory constraints. Criterion values, weights, normalized scores,
assumptions, and missing data are all explicit in the output.
"""

import time
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import MaterialRequirement, WasteListing
from app.services.material_intelligence import taxonomy
from app.services.pathways import templates

OPTIMIZER_VERSION = "pathway-optimizer-v1"

# Normalization direction per criterion: minimize or maximize. Normalized to
# 0-1 with 1 = best for the decision (lower distance/cost is better).
CRITERION_DIRECTION = {
    "environmental_impact": "maximize",
    "distance": "minimize",
    "cost": "minimize",
    "demand": "maximize",
    "feasibility": "maximize",
}

# Alternate weight profiles; the default is explicit and first.
WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "default": {
        "environmental_impact": 0.35,
        "distance": 0.20,
        "cost": 0.20,
        "demand": 0.15,
        "feasibility": 0.10,
    },
    "environment_first": {
        "environmental_impact": 0.55,
        "distance": 0.15,
        "cost": 0.10,
        "demand": 0.10,
        "feasibility": 0.10,
    },
    "cost_first": {
        "environmental_impact": 0.15,
        "distance": 0.15,
        "cost": 0.45,
        "demand": 0.15,
        "feasibility": 0.10,
    },
}
DEFAULT_PROFILE = "default"

DEMAND_CAP = 10  # active requirements in category saturating the demand score


class InfeasibleListing(ValueError):
    """Raised when the listing itself cannot enter any pathway."""


def _distance_score(listing: WasteListing, destination_region: str | None) -> float | None:
    if not destination_region:
        return None
    if destination_region.strip().lower() == (listing.region or "").strip().lower():
        base = 0.3 if (listing.region or "").strip() else None
    else:
        base = 1.0
    return base


def evaluate_pathways(
    db: Session,
    *,
    listing_id,
    destination_region: str | None = None,
    requirement_id=None,
    profile: str = DEFAULT_PROFILE,
) -> dict:
    """Rank feasible pathways for a listing with the Weighted Sum Model."""
    started_tick = time.perf_counter()
    if profile not in WEIGHT_PROFILES:
        raise ValueError(f"Unknown weight profile '{profile}'")

    listing = db.get(WasteListing, listing_id)
    if listing is None:
        raise LookupError("Listing not found")

    requirement = None
    if requirement_id is not None:
        requirement = db.get(MaterialRequirement, requirement_id)
        if requirement is None:
            raise LookupError("Requirement not found")
        destination_region = destination_region or requirement.preferred_region

    destination = destination_region or (requirement.preferred_region if requirement else None)

    # Demand: real data — count active open requirements in the category.
    demand_count = db.query(func.count(MaterialRequirement.id)).filter(
        MaterialRequirement.category == listing.category,
        MaterialRequirement.status == "active",
    ).scalar() or 0
    demand_score = min(demand_count, DEMAND_CAP) / DEMAND_CAP

    assumptions = [
        "Environmental impact is a curated relative prior per pathway "
        f"({templates.PATHWAY_TEMPLATES_VERSION}); it is not measured carbon data — "
        "absolute carbon arrives with EPA WARM factors (Phase 9).",
        "Cost is a processing-intensity proxy applied to the listing's "
        "price_per_unit (if listed); it is not a quoted processing price.",
        "Distance is a region-match proxy multiplied by the pathway's assumed "
        "transport legs; it is not a routed km estimate.",
        "Demand uses the count of currently active requirements in the same "
        "category at run time.",
    ]

    candidates: list[dict] = []
    rejected: list[dict] = []
    for pathway_id in templates.all_pathway_ids():
        feasible, reason = templates.is_feasible(
            pathway_id, listing.category, listing.contamination_notes
        )
        if not feasible:
            rejected.append({"pathway": pathway_id, "reason": reason})
            continue

        environmental = templates.ENVIRONMENTAL_PRIOR[pathway_id]

        distance = _distance_score(listing, destination)
        if distance is not None:
            distance = distance * templates.TRANSPORT_LEGS[pathway_id] / 3.0

        if listing.price_per_unit is not None and listing.price_per_unit > 0:
            cost = min(1.0, templates.COST_MULTIPLIER[pathway_id])
        else:
            cost = None

        feasibility = 1.0
        if listing.contamination_notes:
            feasibility -= templates.CONTAMINATION_PENALTY[pathway_id]

        raw_values = {
            "environmental_impact": environmental,
            "distance": distance,
            "cost": cost,
            "demand": demand_score,
            "feasibility": max(0.0, feasibility),
        }
        candidates.append({
            "pathway": pathway_id,
            "label": templates.PATHWAY_LABELS[pathway_id],
            "steps": templates.REQUIRED_PROCESSING[pathway_id],
            "transport_legs": templates.TRANSPORT_LEGS[pathway_id],
            "raw_values": raw_values,
        })

    if not candidates:
        raise InfeasibleListing(
            f"No feasible pathway for listing in category '{listing.category}' "
            f"with the curated constraints"
        )

    ranked, missing_data = _rank_with_wsm(candidates, profile, listing)

    # Sensitivity: perturb each weight ±25% and check whether the top rank
    # flips. Deterministic, documented, cheap.
    sensitivity = _sensitivity(ranked, profile, listing)

    return {
        "listing_id": str(listing.id),
        "category": listing.category,
        "profile": profile,
        "profiles_available": list(WEIGHT_PROFILES),
        "ranked": ranked,
        "rejected": rejected,
        "assumptions": assumptions,
        "missing_data": missing_data,
        "sensitivity": sensitivity,
        "demand_count": demand_count,
        "destination_region": destination,
        "versions": {
            "optimizer": OPTIMIZER_VERSION,
            "templates": templates.PATHWAY_TEMPLATES_VERSION,
            "taxonomy": taxonomy.TAXONOMY_VERSION,
            "criterion_direction": CRITERION_DIRECTION,
        },
        "runtime_ms": int((time.perf_counter() - started_tick) * 1000),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _rank_with_wsm(candidates: list[dict], profile: str, listing: WasteListing):
    """Apply the Weighted Sum Model with renormalization over available data."""
    weights = dict(WEIGHT_PROFILES[profile])
    missing_data: dict[str, str] = {}

    # A criterion that is None for ALL candidates is dropped with documented
    # renormalization (blueprint: missing values explicit, not zeros).
    for criterion in list(weights):
        if all(candidate["raw_values"].get(criterion) is None for candidate in candidates):
            missing_data[criterion] = (
                "No data available for this criterion on any candidate; "
                "criterion dropped and weights renormalized"
            )
            del weights[criterion]

    total_weight = sum(weights.values())
    renormalized = {c: w / total_weight for c, w in weights.items()}

    # Criterion values may differ per candidate; min-max normalize within the
    # candidate set where a spread exists, else use the raw value direction.
    normalized: dict[str, dict[str, float]] = {}
    for criterion in renormalized:
        values = {
            candidate["pathway"]: candidate["raw_values"].get(criterion)
            for candidate in candidates
        }
        present = [v for v in values.values() if v is not None]
        if not present:
            continue
        low, high = min(present), max(present)
        for candidate in candidates:
            value = candidate["raw_values"].get(criterion)
            if value is None:
                continue
            if high > low:
                score = (value - low) / (high - low)
            else:
                score = 1.0  # single distinct value: no disadvantage
            if CRITERION_DIRECTION[criterion] == "minimize":
                score = 1.0 - score
            normalized.setdefault(candidate["pathway"], {})[criterion] = round(score, 4)

    ranked = []
    for candidate in candidates:
        per_criterion = normalized.get(candidate["pathway"], {})
        score = sum(
            renormalized[criterion] * per_criterion[criterion]
            for criterion in renormalized if criterion in per_criterion
        )
        ranked.append({
            "pathway": candidate["pathway"],
            "label": candidate["label"],
            "steps": candidate["steps"],
            "transport_legs": candidate["transport_legs"],
            "raw_values": {
                key: (round(value, 4) if value is not None else None)
                for key, value in candidate["raw_values"].items()
            },
            "normalized_values": per_criterion,
            "criterion_weights": {c: round(w, 4) for c, w in renormalized.items()},
            "weighted_contributions": {
                c: round(renormalized[c] * per_criterion[c], 4)
                for c in renormalized if c in per_criterion
            },
            "score": round(score, 4),
            "missing_criteria": [
                c for c in candidate["raw_values"]
                if candidate["raw_values"][c] is None
            ],
        })
    ranked.sort(key=lambda c: (-c["score"], c["pathway"]))
    return ranked, missing_data


def _sensitivity(ranked: list[dict], profile: str, listing: WasteListing) -> list[dict]:
    """Rank-reversal thresholds under ±25% weight perturbation."""
    results = []
    if len(ranked) < 2:
        return results
    top, runner = ranked[0], ranked[1]
    gap = top["score"] - runner["score"]
    for criterion, weight in WEIGHT_PROFILES[profile].items():
        if criterion not in top["criterion_weights"] or criterion not in runner["criterion_weights"]:
            continue
        # Perturb: top loses weight, runner gains it (worst case for the lead).
        w_top = top["criterion_weights"][criterion]
        perturb = weight * 0.25
        # Documented check: the top stays stable while the weighted gap
        # (score difference) exceeds the maximal single-weight perturbation
        # effect on the runner-up.
        effect = perturb * abs(
            top["normalized_values"].get(criterion, 0.0)
            - runner["normalized_values"].get(criterion, 0.0)
        )
        results.append({
            "criterion": criterion,
            "weight": weight,
            "score_gap": round(gap, 4),
            "perturbation": round(perturb, 4),
            "max_perturbation_effect": round(effect, 4),
            "top_rank_stable": bool(gap > effect),
        })
    return results
