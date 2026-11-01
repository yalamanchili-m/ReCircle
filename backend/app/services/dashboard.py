from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MaterialRequirement, Match, User, WasteListing


def build_summary(db: Session, user: User) -> dict:
    """Aggregate dashboard numbers.

    Quantities are grouped by unit and never summed across incompatible units
    (kilograms and litres are not added together).
    """
    org_scoped = not (user.role == "admin" and user.organization_id is None)
    org_id = user.organization_id if org_scoped else None

    active_query = select(WasteListing).where(WasteListing.status == "active")
    requirement_query = select(MaterialRequirement).where(
        MaterialRequirement.status == "active"
    )
    match_query = select(Match).join(
        MaterialRequirement, Match.requirement_id == MaterialRequirement.id
    )
    recent_query = (
        select(WasteListing).order_by(WasteListing.updated_at.desc()).limit(5)
    )

    if org_id is not None:
        active_query = active_query.where(WasteListing.organization_id == org_id)
        requirement_query = requirement_query.where(
            MaterialRequirement.organization_id == org_id
        )
        match_query = match_query.where(MaterialRequirement.organization_id == org_id)
        recent_query = recent_query.where(WasteListing.organization_id == org_id)

    active_listings = db.scalar(
        select(func.count()).select_from(active_query.subquery())
    ) or 0

    unit_rows = db.execute(
        select(
            WasteListing.unit,
            func.sum(WasteListing.quantity),
            func.count(WasteListing.id),
        )
        .where(
            WasteListing.status == "active",
            *([WasteListing.organization_id == org_id] if org_id is not None else []),
        )
        .group_by(WasteListing.unit)
    ).all()
    quantity_by_unit = [
        {"unit": unit, "total": float(total or 0), "listing_count": count}
        for unit, total, count in unit_rows
    ]

    requirements_count = db.scalar(
        select(func.count()).select_from(requirement_query.subquery())
    ) or 0

    matches_count = db.scalar(select(func.count()).select_from(match_query.subquery())) or 0

    recent = db.scalars(recent_query).all()

    return {
        "active_listings": active_listings,
        "quantity_by_unit": quantity_by_unit,
        "requirements_count": requirements_count,
        "matches_count": matches_count,
        "recent_listings": recent,
    }
