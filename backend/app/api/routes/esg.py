from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.services import audit, esg

router = APIRouter()


@router.get("/esg/dashboard")
def esg_dashboard(
    period_from: date | None = Query(default=None),
    period_to: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if period_from is not None and period_to is not None and period_from > period_to:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_from must not be after period_to",
        )
    return esg.build_dashboard(db, current_user, period_from, period_to)


@router.get("/esg/export", response_class=PlainTextResponse)
def esg_export(
    period_from: date | None = Query(default=None),
    period_to: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    if period_from is not None and period_to is not None and period_from > period_to:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_from must not be after period_to",
        )
    csv_text = esg.export_csv(db, current_user, period_from, period_to)
    audit.record_audit(
        db,
        actor=current_user,
        action="esg.export",
        entity_type="esg",
        details={"period_from": str(period_from), "period_to": str(period_to)},
    )
    db.commit()
    filename = f"recircle_esg_export_{period_from or 'all'}_{period_to or 'all'}.csv"
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
