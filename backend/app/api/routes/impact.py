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
    """Factor catalog with full provenance (blueprint: factors/provenance)."""
    return {
        "factor_catalog_version": carbon.FACTOR_CATALOG_VERSION,
        "factor_unit": carbon.FACTOR_UNIT,
        "factor_source": carbon.FACTOR_SOURCE,
        "baseline_reference": carbon.BASELINE_REFERENCE,
        "method": carbon.METHOD,
        "supported_units": sorted(carbon.MASS_UNIT_TO_KG.keys()),
        "baseline_pathway": carbon.BASELINE_PATHWAY,
        "rows": [
            {
                "category": row.category,
                "pathway": row.pathway,
                "value": row.value,
                "uncertainty_ratio": row.uncertainty_ratio,
                "note": row.note,
                "is_baseline": row.pathway == carbon.BASELINE_PATHWAY,
            }
            for row in sorted(carbon.CATALOG.values(), key=lambda r: (r.category, r.pathway))
        ],
        "limitations": carbon.LIMITATIONS,
        "disclaimer": (
            "Curated platform approximation values pending EPA WARM v15 "
            "ingestion (Phase 15); they must not be presented as "
            "EPA-verified numbers."
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
