from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Offer, User
from app.schemas.trade import (
    OfferCreate,
    OfferResponse,
    RecoveryRecordCreate,
    RecoveryRecordResponse,
    TransactionResponse,
)
from app.services import trade

router = APIRouter()


@router.post("/offers", response_model=OfferResponse, status_code=201)
def create_offer(
    payload: OfferCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Offer:
    offer = trade.create_offer(db, current_user, payload)
    db.commit()
    return offer


@router.get("/offers")
def list_offers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items, total = trade.list_offers(db, current_user, page=page, page_size=page_size)
    return {
        "items": [OfferResponse.model_validate(item).model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/offers/{offer_id}/accept", response_model=TransactionResponse)
def accept_offer(
    offer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    transaction = trade.accept_offer(db, current_user, offer_id)
    db.commit()
    return TransactionResponse.model_validate(transaction)


@router.post("/offers/{offer_id}/withdraw", response_model=OfferResponse)
def withdraw_offer(
    offer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OfferResponse:
    offer = trade.withdraw_offer(db, current_user, offer_id)
    db.commit()
    return OfferResponse.model_validate(offer)


@router.get("/transactions")
def list_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items, total = trade.list_transactions(db, current_user, page=page, page_size=page_size)
    return {
        "items": [TransactionResponse.model_validate(item).model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    transaction = trade.get_transaction_for_user(db, transaction_id, current_user)
    return TransactionResponse.model_validate(transaction)


@router.post("/transactions/{transaction_id}/recovery", response_model=RecoveryRecordResponse, status_code=201)
def record_recovery(
    transaction_id: UUID,
    payload: RecoveryRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryRecordResponse:
    recovery = trade.record_recovery(db, current_user, transaction_id, payload)
    db.commit()
    return RecoveryRecordResponse.model_validate(recovery)


@router.post("/recovery-records/{recovery_record_id}/verify", response_model=RecoveryRecordResponse)
def verify_recovery(
    recovery_record_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryRecordResponse:
    recovery = trade.verify_recovery(db, current_user, recovery_record_id)
    db.commit()
    return RecoveryRecordResponse.model_validate(recovery)
