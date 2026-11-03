from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.services import audit, carbon

router = APIRouter()


@router.get("/impact/factors")
def list_factors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Factor catalog with full provenance (blueprint: factors/provenance).

    Serves whichever catalog is active: a validated ingested external set
    (Phase 15) when present, otherwise the curated approximation fallback.
    """
    active = carbon.active_catalog(db)
    db.commit()
    ingested = active["origin"] == "ingested_external"
    return {
        "factor_catalog_version": active["catalog_version"],
        "factor_unit": carbon.FACTOR_UNIT,
        "factor_source": active["factor_source"],
        "baseline_reference": active["baseline_reference"],
        "method": carbon.METHOD,
        "supported_units": sorted(carbon.MASS_UNIT_TO_KG.keys()),
        "baseline_pathway": carbon.BASELINE_PATHWAY,
        "factor_origin": active["origin"],
        "rows": [
            {
                "category": row.category,
                "pathway": row.pathway,
                "value": row.value,
                "uncertainty_ratio": row.uncertainty_ratio,
                "note": row.note,
                "is_baseline": row.pathway == carbon.BASELINE_PATHWAY,
            }
            for row in sorted(active["catalog"].values(), key=lambda r: (r.category, r.pathway))
        ],
        "limitations": carbon.limitation_texts(active["origin"]),
        "disclaimer": (
            "Ingested external factor set is active; values trace to "
            "ingestion runs with recorded provenance."
            if ingested
            else (
                "Curated platform approximation values pending EPA WARM v15 "
                "ingestion (Phase 15); they must not be presented as "
                "EPA-verified numbers."
            )
        ),
    }


@router.post("/impact/recompute", status_code=200)
def recompute_estimates(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Regenerate every current estimate with the active factor catalog.

    Previous estimate rows remain persisted as non-current history, so
    recomputation is traceable and can never double-count in aggregation.
    """
    stats = carbon.recompute_all_estimates(db)
    db.commit()
    audit.record_audit(
        db,
        actor=current_user,
        action="impact.recompute",
        entity_type="impact",
        details=stats,
    )
    db.commit()
    return stats
