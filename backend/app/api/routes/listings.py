from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.schemas.listing import ListingCreate, ListingPage, ListingResponse, ListingUpdate
from app.schemas.passport import (
    PassportCreate,
    PassportResponse,
    PassportReview,
    PassportUpdate,
)
from app.services import audit, inventory, passports

router = APIRouter()


@router.get("/listings", response_model=ListingPage)
def list_listings(
    q: str | None = None,
    listing_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListingPage:
    items, total = inventory.list_listings(
        db,
        user=current_user,
        q=q,
        listing_status=listing_status,
        category=category,
        page=page,
        page_size=page_size,
    )
    return ListingPage(
        items=[ListingResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/listings", response_model=ListingResponse, status_code=status.HTTP_201_CREATED)
def create_listing(
    payload: ListingCreate,
    current_user: User = Depends(require_roles("generator", "admin")),
    db: Session = Depends(get_db),
) -> ListingResponse:
    if current_user.organization is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="User has no organization; cannot create listings",
        )
    listing = inventory.create_listing(db, payload, current_user.organization, current_user)
    audit.record_audit(
        db,
        actor=current_user,
        action="listing.create",
        entity_type="waste_listing",
        entity_id=listing.id,
        details={"title": listing.title, "status": listing.status},
    )
    db.commit()
    return ListingResponse.model_validate(listing)


@router.get("/listings/{listing_id}", response_model=ListingResponse)
def get_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListingResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    return ListingResponse.model_validate(listing)


@router.patch("/listings/{listing_id}", response_model=ListingResponse)
def update_listing(
    listing_id: UUID,
    payload: ListingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListingResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    listing = inventory.update_listing(db, listing, payload)
    audit.record_audit(
        db,
        actor=current_user,
        action="listing.update",
        entity_type="waste_listing",
        entity_id=listing.id,
        details={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    db.commit()
    return ListingResponse.model_validate(listing)


@router.post("/listings/{listing_id}/activate", response_model=ListingResponse)
def activate_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListingResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    listing = inventory.activate_listing(db, listing)
    audit.record_audit(
        db,
        actor=current_user,
        action="listing.activate",
        entity_type="waste_listing",
        entity_id=listing.id,
        details={"title": listing.title},
    )
    db.commit()
    return ListingResponse.model_validate(listing)


@router.post("/listings/{listing_id}/archive", response_model=ListingResponse)
def archive_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ListingResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    listing = inventory.archive_listing(db, listing)
    audit.record_audit(
        db,
        actor=current_user,
        action="listing.archive",
        entity_type="waste_listing",
        entity_id=listing.id,
        details={"title": listing.title},
    )
    db.commit()
    return ListingResponse.model_validate(listing)


@router.post("/listings/{listing_id}/passport", response_model=PassportResponse, status_code=status.HTTP_201_CREATED)
def create_passport(
    listing_id: UUID,
    payload: PassportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PassportResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    passport = passports.create_passport(db, listing, current_user, notes=payload.notes)
    audit.record_audit(
        db,
        actor=current_user,
        action="passport.create",
        entity_type="material_passport",
        entity_id=passport.id,
        details={"listing_id": str(listing.id), "version": passport.version},
    )
    db.commit()
    return PassportResponse.model_validate(passport)


@router.get("/listings/{listing_id}/passport", response_model=PassportResponse)
def get_passport(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PassportResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    passport = passports.get_passport_or_404(db, listing.id)
    return PassportResponse.model_validate(passport)


@router.patch("/listings/{listing_id}/passport", response_model=PassportResponse)
def update_passport(
    listing_id: UUID,
    payload: PassportUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PassportResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    passport = passports.get_passport_or_404(db, listing.id)
    passport = passports.update_passport(db, passport, payload, current_user)
    audit.record_audit(
        db,
        actor=current_user,
        action="passport.update",
        entity_type="material_passport",
        entity_id=passport.id,
        details={"listing_id": str(listing.id), "version": passport.version},
    )
    db.commit()
    return PassportResponse.model_validate(passport)


@router.post("/listings/{listing_id}/passport/review", response_model=PassportResponse)
def review_passport(
    listing_id: UUID,
    payload: PassportReview,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PassportResponse:
    listing = inventory.get_listing_or_404(db, listing_id)
    inventory.assert_can_manage(listing, current_user)
    passport = passports.get_passport_or_404(db, listing.id)
    passport = passports.set_review_status(db, passport, payload.review_status, current_user)
    audit.record_audit(
        db,
        actor=current_user,
        action="passport.review",
        entity_type="material_passport",
        entity_id=passport.id,
        details={"listing_id": str(listing.id), "review_status": passport.review_status},
    )
    db.commit()
    return PassportResponse.model_validate(passport)
