"""Explainable AI Engine (blueprint Phase 10).

A common explanation schema for every explainable subject on the platform:
matches (rule+content scoring), pathway ranking (Weighted Sum Model), and
factor-based impact estimates. For deterministic rule/MCDM subjects the
engine returns NATIVE per-criterion contributions — SHAP/LIME are never
forced onto transparent arithmetic.

Model governance: every explanation carries its schema version, subject
version (algorithm/model), method, caveats, data coverage, and input
references so the explanation corresponds to the exact prediction inputs.
SHAP/LIME are reported as unavailable with reasons until a supported
(tree-based) predictive model is deployed — which requires labelled data
the platform does not have yet.
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

EXPLANATION_SCHEMA_VERSION = "explanation-schema-v1"

METHODS = {
    "match": "native_rule_contributions_with_content_fit",
    "pathway": "native_weighted_sum_contributions",
    "impact_estimate": "factor_arithmetic_replay",
}

MATCH_CAVEATS = [
    "Contributions come from documented deterministic rule weights "
    "(circular-match-v2); no trained model was involved.",
    "Compatibility is decision support only — never proof of chemical, "
    "legal, or process safety.",
]

PATHWAY_CAVEATS = [
    "Contributions come from the Weighted Sum Model (pathway-optimizer-v1): "
    "normalized per-criterion scores multiplied by documented weights.",
    "Hard feasibility rules were applied before scoring; feasibility can "
    "never be overridden by contributions.",
]

IMPACT_CAVEATS = [
    "The estimate is deterministic factor arithmetic; there is no ML model "
    "to explain, so SHAP/LIME do not apply.",
    "Factor differences describe typical substitution patterns for these "
    "categories; they do not prove causation for this specific shipment.",
    "Uncertainty is a worst-case row-level interval, not a statistical "
    "distribution.",
]

CAUSATION_NOTE = (
    "Contributions describe how the scoring formula produced this result; "
    "they are not causal claims about real-world outcomes."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_explanation(
    *,
    subject_type: str,
    subject_version: str,
    inputs: dict[str, Any],
    contributions: list[dict[str, Any]],
    caveats: list[str],
    data_coverage: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict:
    """Common schema container. Contributions carry feature, value, share."""
    total_mass = sum(abs(float(c.get("value", 0) or 0)) for c in contributions)
    normalized = []
    for contribution in contributions:
        share = (
            round(abs(float(contribution["value"])) / total_mass, 4)
            if total_mass > 0
            else 0.0
        )
        normalized.append(
            {
                "feature": contribution.get("feature"),
                "value": contribution.get("value"),
                "unit": contribution.get("unit", "points"),
                "direction": contribution.get("direction", "increased"),
                "share_of_signal": share,
                "detail": contribution.get("detail"),
            }
        )
    explanation = {
        "explanation_schema_version": EXPLANATION_SCHEMA_VERSION,
        "subject_type": subject_type,
        "subject_version": subject_version,
        "method": METHODS[subject_type],
        "method_note": (
            "Native contributions from a transparent deterministic evaluator; "
            "no surrogate local model is fitted."
        ),
        "inputs": inputs,
        "contributions": normalized,
        "caveats": caveats,
        "causation_note": CAUSATION_NOTE,
        "data_coverage": data_coverage,
        "sources": sources or [],
        "generated_at": _now(),
    }
    if extra:
        explanation.update(extra)
    return explanation


def explain_match(candidate_like: Any) -> dict:
    """Common-schema explanation for a stored match snapshot.

    `candidate_like` needs: score_breakdown.{components, max_applicable,
    material_fit, knn_score, algorithm_version, warnings} and optionally
    the human explanation text.
    """
    breakdown = candidate_like.get("score_breakdown", {})
    components = breakdown.get("components", {})
    max_applicable = breakdown.get("max_applicable", 0) or 0
    contributions = []
    for feature, earned in sorted(components.items()):
        applicable = {
            "category": 40.0,
            "quantity": 25.0,
            "quality": 20.0,
            "location": 10.0,
            "price": 5.0,
        }.get(feature, max_applicable or 0)
        contributions.append(
            {
                "feature": feature,
                "value": float(earned),
                "unit": "rule_weight_points",
                "direction": "increased" if float(earned) > 0 else "neutral",
                "detail": (
                    f"{float(earned)} of {applicable:.0f} possible points "
                    f"({round(100 * float(earned) / applicable, 1)}%)"
                    if applicable
                    else "criterion not applicable for this requirement"
                ),
            }
        )
    contributions.append(
        {
            "feature": "material_fit",
            "value": float(breakdown.get("material_fit", 0) or 0),
            "unit": "percent",
            "direction": (
                "increased" if float(breakdown.get("material_fit", 0) or 0) > 0 else "neutral"
            ),
            "detail": "Content-based similarity over normalized material/requirement features",
        }
    )
    contributions.append(
        {
            "feature": "knn_score",
            "value": float(breakdown.get("knn_score", 0) or 0),
            "unit": "percent",
            "direction": (
                "increased" if float(breakdown.get("knn_score", 0) or 0) > 0 else "neutral"
            ),
            "detail": (
                "Weighted transparent feature scoring (quantity 0.35, quality 0.25, "
                "location 0.15, price 0.05, material_fit 0.20; inapplicable features "
                "dropped with renormalization) — used for ranking, not a trained model"
            ),
        }
    )
    warnings = list(breakdown.get("warnings", []))
    return build_explanation(
        subject_type="match",
        subject_version=breakdown.get("algorithm_version", "circular-match-v2"),
        inputs={
            "note": "see stored match record for the requirement/listing inputs",
            "assessment_text": candidate_like.get("explanation"),
        },
        contributions=contributions,
        caveats=MATCH_CAVEATS + (["Warnings: **" + "; ".join(warnings) + "**"] if warnings else []),
        data_coverage={
            "criteria_evaluated": sorted(components.keys()),
            "max_applicable_points": max_applicable,
            "warnings_count": len(warnings),
        },
    )


def explain_pathway(pathway_candidate: dict, profile: str) -> dict:
    """Common-schema explanation for a ranked pathway candidate."""
    weighted = pathway_candidate.get("weighted_contributions", {})
    score = float(pathway_candidate.get("score", 0) or 0)
    contributions = []
    for criterion in sorted(weighted):
        value = float(weighted[criterion])
        contributions.append(
            {
                "feature": criterion,
                "value": value,
                "unit": "weighted_score_points",
                "direction": "increased" if value > 0 else "decreased",
                "detail": (
                    f"weighted contribution to total score "
                    f"{round(value / score * 100, 1) if score else 0}% of final ranking score"
                    if score
                    else "weighted contribution"
                ),
            }
        )
    fine: dict[str, Any] = {}
    if pathway_candidate.get("rejected_reason"):
        fine["rejected"] = pathway_candidate["rejected_reason"]
    return build_explanation(
        subject_type="pathway",
        subject_version=PATHWAY_VERSION,
        inputs={
            "pathway": pathway_candidate.get("pathway"),
            "profile": profile,
            "raw_values": pathway_candidate.get("raw_values"),
            "normalized_values": pathway_candidate.get("normalized_values"),
            "criterion_weights": pathway_candidate.get("criterion_weights"),
        },
        contributions=contributions,
        caveats=PATHWAY_CAVEATS,
        data_coverage={
            "missing_criteria": pathway_candidate.get("missing_criteria", []),
            "total_score": score,
        },
        extra=fine,
    )


PATHWAY_VERSION = "pathway-optimizer-v1"


def explain_impact(estimate: Any, category: str | None = None) -> dict:
    """Common-schema explanation for a factor-based impact estimate.

    Contributions are the signed formula terms (their sum equals the
    estimate), plus the factor provenance and the uncertainty band.
    """
    supported = bool(getattr(estimate, "supported", False))
    assumptions = getattr(estimate, "assumptions", {}) or {}
    formula_terms = assumptions.get("formula_terms", [])
    contributions = []
    if supported and formula_terms:
        for term in formula_terms:
            contributions.append(
                {
                    "feature": term["term"],
                    "value": term["signed_contribution_kg"],
                    "unit": "kg_co2e",
                    "direction": (
                        "increased"
                        if float(term["signed_contribution_kg"]) > 0
                        else "decreased"
                    ),
                    "detail": (
                        f"factor {term['factor']} {term['unit']} multiplied by recovered tonnes"
                    ),
                }
            )
    else:
        contributions.append(
            {
                "feature": "estimate_unavailable",
                "value": 0.0,
                "unit": "kg_co2e",
                "direction": "neutral",
                "detail": (
                    getattr(estimate, "unsupported_reason", None)
                    or "No estimate stored for this recovery record"
                ),
            }
        )
    return build_explanation(
        subject_type="impact_estimate",
        subject_version=(
            f"{getattr(estimate, 'method', 'factor_differential_v1')} | "
            f"{getattr(estimate, 'factor_catalog_version', '')}".strip()
        ),
        inputs={
            "recovery_record_id": str(getattr(estimate, "recovery_record_id", "")),
            "recovery_route": getattr(estimate, "recovery_route", None),
            "quantity": getattr(estimate, "quantity", None),
            "unit": getattr(estimate, "unit", None),
            "quantity_tonnes": (
                float(estimate.quantity_tonnes) if estimate.quantity_tonnes is not None else None
            )
            if estimate is not None
            else None,
            "category": category,
            "estimate_id": str(getattr(estimate, "id", "")),
        },
        contributions=contributions,
        caveats=IMPACT_CAVEATS + [
            caveat
            for caveat in list(assumptions.get("limitations", []))
            if "causation" in caveat
        ],
        data_coverage={
            "supported": supported,
            "avoided_co2e_kg": (
                float(estimate.avoided_co2e_kg) if estimate.avoided_co2e_kg is not None else None
            )
            if estimate is not None
            else None,
            "uncertainty_band": {
                "low_kg": assumptions.get("avoided_co2e_kg_low"),
                "high_kg": assumptions.get("avoided_co2e_kg_high"),
                "basis": assumptions.get("uncertainty_basis"),
            }
            if supported
            else None,
            "baseline_reference": getattr(estimate, "baseline_reference", None),
        },
        sources=[
            {
                "type": "factor_catalog",
                "version": getattr(estimate, "factor_catalog_version", None),
                "source": getattr(estimate, "factor_source", None),
            }
        ],
    )


def explain_subject_status() -> dict:
    """Model governance / SHAP-LIME support status."""
    return {
        "explanation_schema_version": EXPLANATION_SCHEMA_VERSION,
        "predictive_models_deployed": False,
        "shap": {
            "status": "not_applicable",
            "reason": (
                "No supported tree-based predictive model is deployed. "
                "Random Forest/XGBoost require labelled training data the "
                "platform does not have (blueprint forbids training on "
                "synthetic rows)."
            ),
        },
        "lime": {
            "status": "not_applicable",
            "reason": (
                "No opaque predictive model exists to approximate; the "
                "deterministic subjects expose native contributions instead, "
                "which outperform LIME on faithful reconstruction."
            ),
        },
        "note": (
            "Match/pathway/impact subjects are deterministic and expose "
            "native per-criterion/per-term contributions directly."
        ),
        "limitations": LIMITATIONS_LIST,
    }


LIMITATIONS_LIST = [
    "Explanations correspond to the deterministic evaluators' own inputs "
    "and only to them: recomputing with different inputs yields different "
    "explanations.",
    "SHAP/LIME activate only if/when a supported predictive model with "
    "labelled data ships.",
    "No correlation-as-causation language is used; contributions always "
    "describe formula behaviour and are labelled as such.",
]
