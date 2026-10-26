from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Organization, User, WasteListing
from app.schemas.listing import ListingCreate, ListingUpdate

ACTIVE_REQUIRED_FIELDS = ("title", "description", "category", "city")


def get_listing_or_404(db: Session, listing_id: UUID) -> WasteListing:
    listing = db.get(WasteListing, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return listing


def assert_can_manage(listing: WasteListing, user: User) -> None:
    """Only the owner organization (or admin) may manage a listing."""
    if user.role == "admin":
        return
    if user.organization_id is None or listing.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner organization may manage this listing",
        )


def list_listings(
    db: Session,
    user: User,
    q: str | None = None,
    listing_status: str | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WasteListing], int]:
    query = select(WasteListing)
    if user.role == "admin" and user.organization_id is None:
        pass  # admin without org sees all
    else:
        query = query.where(WasteListing.organization_id == user.organization_id)

    if q:
        pattern = f"%{q}%"
        query = query.where(
            WasteListing.title.ilike(pattern) | WasteListing.description.ilike(pattern)
        )
    if listing_status:
        query = query.where(WasteListing.status == listing_status)
    if category:
        query = query.where(WasteListing.category == category)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(WasteListing.created_at.desc(), WasteListing.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def create_listing(
    db: Session, data: ListingCreate, organization: Organization, user: User
) -> WasteListing:
    listing = WasteListing(
        **data.model_dump(),
        organization_id=organization.id,
        created_by=user.id,
        status="draft",
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def update_listing(db: Session, listing: WasteListing, data: ListingUpdate) -> WasteListing:
    if listing.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Archived listings cannot be edited"
        )
    updates = data.model_dump(exclude_unset=True)
    if updates:
        for field, value in updates.items():
            setattr(listing, field, value)
        db.commit()
        db.refresh(listing)
    return listing


def activate_listing(db: Session, listing: WasteListing) -> WasteListing:
    if listing.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Listing is already active"
        )
    if listing.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Archived listings cannot be activated"
        )

    missing = [
        field for field in ACTIVE_REQUIRED_FIELDS if not getattr(listing, field, None)
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required fields for an active listing: {', '.join(missing)}",
        )
    if listing.quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quantity must be greater than zero to activate",
        )

    listing.status = "active"
    db.commit()
    db.refresh(listing)
    return listing


def archive_listing(db: Session, listing: WasteListing) -> WasteListing:
    if listing.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Listing is already archived"
        )
    listing.status = "archived"
    db.commit()
    db.refresh(listing)
    return listing
