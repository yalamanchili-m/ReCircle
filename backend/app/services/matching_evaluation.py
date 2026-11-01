"""Scenario evaluation for the Circular Match Engine (blueprint Phase 5).

Curated, versioned synthetic scenarios verify that the rule baseline and the
KNN re-rank produce the expected best candidate. Synthetic labels only —
these metrics verify engine behavior, not real-world accuracy. No labels are
fabricated beyond the explicit expected relationships stated in each
scenario.
"""

from types import SimpleNamespace
from uuid import uuid4

from app.services.matching import KNN_FEATURE_WEIGHTS, ALGORITHM_VERSION, rank_candidates, score_candidate

EVAL_SET_VERSION = "matching-scenario-eval-v1"

DISCLAIMER = (
    "Synthetic scenario set for engine verification only; not a measure of "
    "real-world accuracy."
)

DECIMAL = __import__("decimal").Decimal


def _requirement(**overrides):
    defaults = dict(
        id=None,
        title="Scenario requirement",
        description="Synthetic requirement",
        organization_id=None,
        created_by=None,
        category="metals",
        min_quantity=DECIMAL("500.000"),
        unit="kg",
        required_grade="Low carbon steel",
        max_price_per_unit=DECIMAL("22.00"),
        preferred_city="Pune",
        preferred_region="Maharashtra",
        status="active",
        created_at=None,
        updated_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _listing(**overrides):
    defaults = dict(
        id=None,
        title="Scenario listing",
        description="Synthetic listing",
        organization_id=None,
        created_by=None,
        category="metals",
        material_name=None,
        composition=None,
        grade="Low carbon steel",
        condition=None,
        contamination_notes=None,
        quantity=DECIMAL("600.000"),
        unit="kg",
        price_per_unit=DECIMAL("18.00"),
        currency="INR",
        city="Pune",
        region="Maharashtra",
        country="India",
        available_from=None,
        status="active",
        created_at=None,
        updated_at=None,
        organization=SimpleNamespace(name="Scenario Org"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# (scenario_id, requirement kwargs, [listing kwargs...], expected top listing title)
SCENARIOS: list[tuple[str, dict, list[dict], str]] = [
    (
        "exact-beats-partial",
        {},
        [
            {"title": "Partial quantity", "quantity": DECIMAL("250.000")},
            {"title": "Exact match", "quantity": DECIMAL("800.000")},
        ],
        "Exact match",
    ),
    (
        "grade-mismatch-loses",
        {},
        [
            {"title": "Wrong grade", "grade": "Tool steel H13", "quantity": DECIMAL("900.000")},
            {"title": "Right grade", "quantity": DECIMAL("600.000")},
        ],
        "Right grade",
    ),
    (
        "over-budget-excluded",
        {},
        [
            {"title": "Too expensive", "price_per_unit": DECIMAL("99.00")},
            {"title": "Affordable", "price_per_unit": DECIMAL("20.00")},
        ],
        "Affordable",
    ),
    (
        "unit-normalized-quantity",
        {"min_quantity": DECIMAL("500.000"), "unit": "kg"},
        [
            {"title": "One tonne", "quantity": DECIMAL("1.000"), "unit": "tonne"},
            {"title": "Half tonne", "quantity": DECIMAL("500.000"), "unit": "kg"},
        ],
        "One tonne",
    ),
    (
        "material-fit-prefers-copper",
        {
            "title": "Copper winding scrap supply",
            "description": "Copper winding scrap from motors",
            "required_grade": None,
            "max_price_per_unit": None,
            "preferred_city": None,
            "preferred_region": None,
        },
        [
            {"title": "Copper windings", "description": "Copper winding scrap from motors"},
            {"title": "Mixed steel scrap", "description": "Assorted steel offcuts"},
        ],
        "Copper windings",
    ),
]


def _evaluate_method(method: str) -> dict:
    top1 = 0
    for _scenario_id, requirement_kwargs, listing_kwargs, expected_title in SCENARIOS:
        requirement = _requirement(**requirement_kwargs)
        candidates = []
        for index, kwargs in enumerate(listing_kwargs):
            listing = _listing(id=uuid4(), **kwargs)
            candidate = score_candidate(requirement, listing)
            if candidate is not None:
                candidates.append(candidate)
        ranked = rank_candidates(requirement, candidates)
        if ranked and ranked[0].title == expected_title:
            top1 += 1
    return {
        "scenarios": len(SCENARIOS),
        "top1_accuracy": round(top1 / len(SCENARIOS), 4),
        "precision_recall_on_real_data": None,
    }


def evaluate_matching() -> dict:
    return {
        "eval_set": EVAL_SET_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "knn_feature_weights": KNN_FEATURE_WEIGHTS,
        "methods": {
            "rule_baseline": _evaluate_method("rule"),
            "knn_rerank": _evaluate_method("knn"),
        },
        "disclaimer": DISCLAIMER,
    }
