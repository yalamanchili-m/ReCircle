from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WasteListing


def search_active_listings(
    db: Session,
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    region: str | None = None,
    min_quantity: Decimal | None = None,
    unit: str | None = None,
    max_price: Decimal | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WasteListing], int]:
    """Search active listings. Draft, matched, and archived listings never appear."""
    query = select(WasteListing).where(WasteListing.status == "active")

    if q:
        pattern = f"%{q}%"
        query = query.where(
            WasteListing.title.ilike(pattern) | WasteListing.description.ilike(pattern)
        )
    if category:
        query = query.where(WasteListing.category == category)
    if city:
        query = query.where(WasteListing.city.ilike(city))
    if region:
        query = query.where(WasteListing.region.ilike(region))
    if min_quantity is not None:
        query = query.where(WasteListing.quantity >= min_quantity)
    if unit:
        # Quantities are only comparable within the same unit; filter listings to
        # the requested unit instead of mixing kilograms with litres etc.
        query = query.where(WasteListing.unit == unit)
    if max_price is not None:
        # Listings without a price cannot be verified against a budget, so they
        # are excluded when a maximum price filter is applied.
        query = query.where(
            WasteListing.price_per_unit.is_not(None)
            & (WasteListing.price_per_unit <= max_price)
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(WasteListing.created_at.desc(), WasteListing.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def get_active_listing_or_404(db: Session, listing_id) -> WasteListing:
    from fastapi import HTTPException, status

    listing = db.get(WasteListing, listing_id)
    if listing is None or listing.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active listing not found",
        )
    return listing
