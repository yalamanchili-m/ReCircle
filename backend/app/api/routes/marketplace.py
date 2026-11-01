from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.listing import ListingResponse
from app.schemas.passport import PassportPublicResponse
from app.services import marketplace, passports

router = APIRouter()


class MarketplaceListingDetail(ListingResponse):
    organization_name: str



@router.get("/marketplace/listings")
def search_marketplace(
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    region: str | None = None,
    min_quantity: Decimal | None = Query(default=None, gt=0),
    unit: str | None = None,
    max_price: Decimal | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items, total = marketplace.search_active_listings(
        db,
        q=q,
        category=category,
        city=city,
        region=region,
        min_quantity=min_quantity,
        unit=unit,
        max_price=max_price,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [ListingResponse.model_validate(item).model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/marketplace/listings/{listing_id}", response_model=MarketplaceListingDetail)
def get_public_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarketplaceListingDetail:
    listing = marketplace.get_active_listing_or_404(db, listing_id)
    detail = ListingResponse.model_validate(listing).model_dump()
    detail["organization_name"] = listing.organization.name
    return MarketplaceListingDetail.model_validate(detail)


@router.get(
    "/marketplace/listings/{listing_id}/passport", response_model=PassportPublicResponse
)
def get_public_passport(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PassportPublicResponse:
    """Read-only passport for an active listing (blueprint Phase 3).

    Available only for active listings; drafts and archived listings expose
    nothing. Provenance fields let the UI mark values as provided, derived,
    AI-suggested, or unverified.
    """
    listing = marketplace.get_active_listing_or_404(db, listing_id)
    passport = passports.get_active_passport(db, listing.id)
    if passport is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Passport not found for this listing")
    return PassportPublicResponse.model_validate(passport)
