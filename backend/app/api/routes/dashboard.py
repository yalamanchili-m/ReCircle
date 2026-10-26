from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.listing import ListingResponse
from app.services import dashboard

router = APIRouter()


@router.get("/dashboard/summary")
def dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    summary = dashboard.build_summary(db, current_user)
    summary["recent_listings"] = [
        ListingResponse.model_validate(item).model_dump()
        for item in summary["recent_listings"]
    ]
    return summary
