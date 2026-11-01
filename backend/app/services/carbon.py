"""Factor-based carbon impact estimation (blueprint Phase 9).

Differential arithmetic with explicit boundaries:

    avoided_co2e_kg = (baseline_landfill_intensity - route_intensity) x tonnes

Both factors come from the same versioned catalog with the same metric
tonne basis and the same assumed system boundary, so the difference is a
like-for-like comparison. Landfill route = baseline =
zero by construction (nothing is avoided when the material is landfilled).

Resource savings: landfill diversion = recovered mass (mass units only).

Trained ML: Random Forest / XGBoost remain unimplemented
until labelled data exists (blueprint forbids training on synthetic rows).

UNCERTAINTY: every catalog row carries an uncertainty_ratio; the avoided
value carries a worst-case band from interval arithmetic over both terms
(low value with baseline reduced by its ratio and the route increased by
its ratio, and symmetrically). This is stated, not hidden.

FACTOR PROVENANCE: values are a clearly-labelled curated platform
approximation (category-level, round numbers). Real EPA WARM v15 rows
arrive via Phase 15 ingestion and must replace these; until then, no
estimate may be presented as an EPA-verified number.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImpactEstimate, RecoveryRecord

FACTOR_CATALOG_VERSION = "factor-catalog-v2-differential"
FACTOR_SOURCE = "Curated platform approximation pending EPA WARM v15 ingestion (Phase 15)"
FACTOR_UNIT = "kg_co2e_per_metric_tonne"
BASELINE_PATHWAY = "landfill"
BASELINE_REFERENCE = (
    "Regional landfill baseline (no gas-capture system assumed); differential "
    "against the same boundary"
)
METHOD = "factor_differential_v1"
DEFAULT_UNCERTAINTY_RATIO = 0.35
LANDFILL_UNCERTAINTY_RATIO = 0.50

LIMITATIONS = [
    "Placeholder factor set pending EPA WARM v15 ingestion (Phase 15).",
    "Category-level averages; material-specific factors (e.g. aluminium vs "
    "steel) arrive with the real factor catalog.",
    "No transport-distance emissions are included yet.",
    "Uncertainty bands are worst-case row-level intervals, not statistical "
    "distributions; treat values as indicative only.",
    "Factor differences describe typical substitution patterns observed for "
    "these categories; they do not prove causation for a specific shipment.",
]

CREDIT_DISCLAIMERS = [
    "Green-credit figures are an INDICATIVE visualization of environmental "
    "benefit computed from openly documented arithmetic.",
    "They are not official credits: no certification, jurisdictional "
    "programme, tradability, monetary value, or regulatory recognition is "
    "implied.",
    "An authorized credit programme/integration would be required before "
    "any real credit claim.",
]

# Mass units convertible to tonnes for impact math. litre/unit quantities are
# never converted — an estimate for them would require a density/count that
# the platform does not have, so they are unsupported by design.
MASS_UNIT_TO_KG = {"kg": Decimal("1"), "tonne": Decimal("1000")}


@dataclass(frozen=True)
class FactorRow:
    """One catalog row: emission intensity per metric tonne."""

    category: str
    pathway: str
    value: float  # kg CO2e per metric tonne; negative = net credit
    uncertainty_ratio: float
    note: str

    @property
    def display_value(self) -> float:
        return float(self.value)


def _rows() -> list[FactorRow]:
    rows: list[FactorRow] = []
    # Curated approximations: round numbers chosen to be plausible-order
    # values for each category; REJECTED as authoritative until Phase 15.
    lifted: dict[str, dict[str, tuple[float, str] | None]] = {
        # category: pathway -> (value, note) | None (no route defined)
        "paper_cardboard": {
            BASELINE_PATHWAY: (670.0, "Anaerobic decomposition CH4, no gas capture"),
            "recycle": (-900.0, "Virgin pulp/fibre substitution credit"),
            "compost": (-250.0, "Peat/soil-amendment substitution credit"),
            "reuse": None,
            "energy_recovery": None,
        },
        "plastics": {
            BASELINE_PATHWAY: (35.0, "Petrochemical mostly inert at rest"),
            "recycle": (-1250.0, "Virgin polymer substitution credit"),
            "reuse": (-250.0, "Limited direct reuse scenarios"),
            "energy_recovery": (-40.0, "Heat displacement credit"),
            "compost": None,
        },
        "wood": {
            BASELINE_PATHWAY: (520.0, "Anaerobic decomposition CH4, no gas capture"),
            "reuse": (-950.0, "Timber product substitution credit"),
            "recycle": (-350.0, "Chip/aggregate/fibre substitution credit"),
            "compost": (-300.0, "Soil-amendment substitution credit"),
            "energy_recovery": (-120.0, "Heat displacement credit"),
        },
        "metals": {
            BASELINE_PATHWAY: (12.0, "Chemically stable at rest"),
            "reuse": (-1600.0, "Re-entry of steel/aluminium products"),
            "recycle": (-1850.0, "Category-average remelt credit"),
            "compost": None,
            "energy_recovery": None,
        },
        "glass": {
            BASELINE_PATHWAY: (12.0, "Chemically stable at rest"),
            "reuse": (-90.0, "Limited direct reuse scenarios"),
            "recycle": (-330.0, "Cullet substitution credit"),
            "compost": None,
            "energy_recovery": None,
        },
        "textiles": {
            BASELINE_PATHWAY: (380.0, "Mixed-fibre decomposition"),
            "reuse": (-3800.0, "Second-hand garment substitution credit"),
            "recycle": (-800.0, "Fibre-to-fibre/downstream credit"),
            "compost": None,
            "energy_recovery": None,
        },
        "organics": {
            BASELINE_PATHWAY: (920.0, "Dominant CH4, no gas capture"),
            "compost": (-380.0, "Soil-amendment substitution credit"),
            "reuse": None,
            "recycle": None,
            "energy_recovery": None,
        },
        "electronics": {
            BASELINE_PATHWAY: (15.0, "Chemically stable at rest"),
            "reuse": (-950.0, "Refurbished-device substitution credit"),
            "recycle": (-1300.0, "Category-average metal credit"),
            "compost": None,
            "energy_recovery": None,
        },
        "chemicals": {
            BASELINE_PATHWAY: (20.0, "Placeholder pending regulatory review"),
            # No recovery routes defined for chemicals yet: explicitly
            # unsupported rather than guessed.
            "reuse": None,
            "recycle": None,
            "compost": None,
            "energy_recovery": None,
        },
        "other": {
            BASELINE_PATHWAY: (25.0, "Placeholder pending data supply"),
            "reuse": None,
            "recycle": None,
            "compost": None,
            "energy_recovery": None,
        },
    }
    for category, pathways in lifted.items():
        for pathway, spec in pathways.items():
            if spec is None:
                continue
            value, note = spec
            rows.append(
                FactorRow(
                    category=category,
                    pathway=pathway,
                    value=value,
                    uncertainty_ratio=(
                        LANDFILL_UNCERTAINTY_RATIO
                        if pathway == BASELINE_PATHWAY
                        else DEFAULT_UNCERTAINTY_RATIO
                    ),
                    note=note,
                )
            )
    return rows


CATALOG: dict[tuple[str, str], FactorRow] = {(r.category, r.pathway): r for r in _rows()}

ASSUMPTIONS = [
    "avoided = (landfill baseline intensity - route intensity) x recovered "
    "metric tonnes; both factors share the same boundary and unit basis.",
    "Landfill route therefore yields zero avoided emissions and zero "
    "diversion by construction (baseline case).",
    "Uncertainty: worst-case interval over row-level uncertainty ratios "
    "applied to both terms (uncertainty_band in the persisted estimate).",
    "Only mass units (kg, tonne) are convertible; litre/unit quantities "
    "cannot be estimated without density or item weights and are marked "
    "unsupported.",
    "Factors are curated platform approximations; they are NOT EPA-hosted "
    "values until Phase 15 ingests EPA WARM v15.",
]

Q3 = Decimal("0.001")
Q6 = Decimal("0.000001")


def _row(category: str, pathway: str) -> FactorRow | None:
    return CATALOG.get((category, pathway))


def compute_estimate(
    category: str, route: str, quantity: Decimal, unit: str
) -> dict:
    """Deterministic pure computation. Returns estimate fields without persisting."""
    if route == BASELINE_PATHWAY:
        return {
            "supported": True,
            "unsupported_reason": None,
            "recovery_route": route,
            "quantity": quantity,
            "unit": unit,
            "quantity_tonnes": None,
            "avoided_co2e_kg": Decimal("0.000"),
            "avoided_co2e_kg_low": Decimal("0.000"),
            "avoided_co2e_kg_high": Decimal("0.000"),
            "landfill_diverted_kg": Decimal("0.000"),
            "formula_terms": [],
            "reason": "Landfill is the baseline; nothing is avoided by construction",
        }

    baseline = _row(category, BASELINE_PATHWAY)
    factor_route = None if route == "other" else _row(category, route)

    supported = True
    reason = None

    if unit not in MASS_UNIT_TO_KG:
        supported = False
        reason = (
            f"Unit '{unit}' is not convertible to mass; impact estimation "
            "requires kg or tonne"
        )
    elif baseline is None:
        supported = False
        reason = f"No landfill baseline factor curated for category '{category}' yet"
    elif route == "other":
        supported = False
        reason = "Route 'other' has no defined impact pathway"
    elif factor_route is None:
        supported = False
        reason = (
            f"No curated factor for category '{category}' via route '{route}'"
        )

    if not supported:
        return {
            "supported": False,
            "unsupported_reason": reason,
            "recovery_route": route,
            "quantity": quantity,
            "unit": unit,
            "quantity_tonnes": None,
            "avoided_co2e_kg": None,
            "avoided_co2e_kg_low": None,
            "avoided_co2e_kg_high": None,
            "landfill_diverted_kg": None,
            "formula_terms": [],
        }

    kg = quantity * MASS_UNIT_TO_KG[unit]
    tonnes = (kg / Decimal("1000")).quantize(Q6)
    base_term = (Decimal(str(baseline.value)) * tonnes).quantize(Q3, ROUND_HALF_UP)
    route_term = (Decimal(str(factor_route.value)) * tonnes).quantize(Q3, ROUND_HALF_UP)
    avoided = (base_term - route_term).quantize(Q3, ROUND_HALF_UP)

    # Worst-case interval over row-level uncertainty ratios.
    r_base = Decimal(str(baseline.uncertainty_ratio))
    r_route = Decimal(str(factor_route.uncertainty_ratio))
    base_abs = abs(base_term)
    route_abs = abs(route_term)
    band = (base_abs * r_base + route_abs * r_route).quantize(Q3, ROUND_HALF_UP)
    low = avoided - band
    high = avoided + band

    return {
        "supported": True,
        "unsupported_reason": None,
        "recovery_route": route,
        "quantity": quantity,
        "unit": unit,
        "quantity_tonnes": tonnes,
        "avoided_co2e_kg": avoided,
        "avoided_co2e_kg_low": low.quantize(Q3, ROUND_HALF_UP),
        "avoided_co2e_kg_high": high.quantize(Q3, ROUND_HALF_UP),
        "landfill_diverted_kg": kg.quantize(Q3, ROUND_HALF_UP),
        "formula_terms": [
            {
                "term": f"baseline ({BASELINE_PATHWAY}) intensity",
                "factor": float(baseline.value),
                "unit": FACTOR_UNIT,
                "source": FACTOR_SOURCE,
                "signed_contribution_kg": float(base_term),
            },
            {
                "term": f"route ({route}) intensity",
                "factor": float(factor_route.value),
                "unit": FACTOR_UNIT,
                "source": FACTOR_SOURCE,
                "signed_contribution_kg": float(-route_term),
            },
        ],
    }


def estimate_and_persist(
    db: Session, recovery_record: RecoveryRecord, category: str
) -> ImpactEstimate:
    """Compute the estimate for a recovery record and persist it as current.

    Previous current rows for the same record are demoted so aggregation
    can never double-count. Safe to call again after factor updates.
    """
    from app.services import carbon as carbon_module

    existing = db.scalars(
        select(ImpactEstimate).where(
            ImpactEstimate.recovery_record_id == recovery_record.id,
            ImpactEstimate.is_current.is_(True),
        )
    ).all()
    for old in existing:
        old.is_current = False
    if existing:
        db.flush()  # release the partial unique index slot before inserting

    computed = carbon_module.compute_estimate(
        category,
        recovery_record.recovery_route or "other",
        recovery_record.recovered_quantity,
        recovery_record.unit,
    )
    estimate = ImpactEstimate(
        recovery_record_id=recovery_record.id,
        supported=computed["supported"],
        unsupported_reason=computed["unsupported_reason"],
        recovery_route=computed["recovery_route"],
        quantity=computed["quantity"],
        unit=computed["unit"],
        quantity_tonnes=computed["quantity_tonnes"],
        avoided_co2e_kg=computed["avoided_co2e_kg"],
        landfill_diverted_kg=computed["landfill_diverted_kg"],
        method=METHOD,
        factor_catalog_version=FACTOR_CATALOG_VERSION,
        factor_source=FACTOR_SOURCE,
        baseline_reference=BASELINE_REFERENCE,
        assumptions={
            "items": ASSUMPTIONS,
            "limitations": LIMITATIONS,
            "formula_terms": computed.get("formula_terms", []),
            "avoided_co2e_kg_low": (
                float(computed["avoided_co2e_kg_low"])
                if computed["avoided_co2e_kg_low"] is not None
                else None
            ),
            "avoided_co2e_kg_high": (
                float(computed["avoided_co2e_kg_high"])
                if computed["avoided_co2e_kg_high"] is not None
                else None
            ),
            "uncertainty_basis": (
                "worst-case interval over row-level uncertainty ratios "
                f"(landfill ±{int(LANDFILL_UNCERTAINTY_RATIO * 100)}%, "
                f"routes ±{int(DEFAULT_UNCERTAINTY_RATIO * 100)}%)"
            ),
        },
        is_current=True,
    )
    db.add(estimate)
    db.flush()
    return estimate


def validate_factor_catalog(rows: list[dict]) -> dict:
    """Validate an ingested factor set (used by Phase 15 ingestion too).

    Accepts structured rows of
    {category, pathway, quantity_kg_co2e_per_tonne, uncertainty_ratio?, note?}.
    Rejects invalid/duplicate rows with explicit reasons; checks that every
    category with any route row also carries a landfill baseline.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        reason = None
        category = row.get("category")
        pathway = row.get("pathway")
        value = row.get("quantity_kg_co2e_per_tonne")
        uncertainty = row.get("uncertainty_ratio", DEFAULT_UNCERTAINTY_RATIO)

        if not isinstance(category, str) or not category.strip():
            reason = "category missing or invalid"
        elif not isinstance(pathway, str) or not pathway.strip():
            reason = "pathway missing or invalid"
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            reason = f"invalid value {value!r}: must be a number ({FACTOR_UNIT})"
        elif not isinstance(uncertainty, (int, float)) or not (0 <= float(uncertainty) <= 1):
            reason = f"invalid uncertainty_ratio {uncertainty!r}: must be within [0, 1]"
        elif (category, pathway) in seen:
            reason = f"duplicate row for ({category}, {pathway})"

        if reason is not None:
            rejected.append({"row": row, "reason": reason})
            continue
        seen.add((category, pathway))
        accepted.append(
            {
                "category": category.strip(),
                "pathway": pathway.strip(),
                "value": float(value),
                "uncertainty_ratio": float(uncertainty),
            }
        )

    categories_with_routes = {
        row["category"] for row in accepted if row["pathway"] != BASELINE_PATHWAY
    }
    categories_with_baseline = {
        row["category"] for row in accepted if row["pathway"] == BASELINE_PATHWAY
    }
    missing_baseline = sorted(categories_with_routes - categories_with_baseline)

    return {
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejected": rejected,
        "missing_baseline_categories": missing_baseline,
        "factor_unit": FACTOR_UNIT,
        "note": (
            "A factor set passes validation only when no rows are rejected "
            "with reasons and every category with recovery routes also "
            "carries a landfill baseline."
        ),
    }


def recompute_all_estimates(db: Session) -> dict:
    """Regenerate the current estimate for every recovery record.

    The listing category is resolved through the trade chain so the newest
    catalog governs every estimate with full traceability (previous versions
    remain persisted as non-current history).
    """
    from sqlalchemy import func

    from app.models import Offer, Transaction, WasteListing

    chain = (
        select(ImpactEstimate, WasteListing.category)
        .join(RecoveryRecord, ImpactEstimate.recovery_record_id == RecoveryRecord.id)
        .join(Transaction, RecoveryRecord.transaction_id == Transaction.id)
        .join(Offer, Transaction.offer_id == Offer.id)
        .join(WasteListing, Offer.listing_id == WasteListing.id)
        .where(ImpactEstimate.is_current.is_(True))
    )

    recomputed = 0
    unsupported = 0
    failed = 0
    for estimate, category in db.execute(chain).all():
        recovery = db.get(RecoveryRecord, estimate.recovery_record_id)
        if recovery is None:  # pragma: no cover
            failed += 1
            continue
        try:
            fresh = estimate_and_persist(db, recovery, category)
            recomputed += 1
            if not fresh.supported:
                unsupported += 1
        except Exception:  # noqa: BLE001 - per-row failure must not abort the run
            failed += 1

    return {
        "recomputed": recomputed,
        "unsupported": unsupported,
        "failed": failed,
        "total_recovery_records": db.scalar(
            select(func.count()).select_from(RecoveryRecord)
        )
        or 0,
        "catalog_version": FACTOR_CATALOG_VERSION,
        "method": METHOD,
    }


def green_credit_points(
    landfill_diverted_kg: float | None, avoided_co2e_kg: float | None
) -> int:
    """Documented indicative formula: 1 point per kg material diverted + 1 point per kg CO2e avoided."""
    return int(round(float(landfill_diverted_kg or 0) + float(avoided_co2e_kg or 0)))
