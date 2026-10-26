from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import OrganizationSummary
from app.schemas.organization import OrganizationResponse, OrganizationUpdate
from app.services import audit

router = APIRouter()


def _current_organization(user: User):
    if user.organization is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User has no organization"
        )
    return user.organization


@router.get("/organizations/me", response_model=OrganizationResponse)
def read_my_organization(current_user: User = Depends(get_current_user)):
    return _current_organization(current_user)


@router.patch("/organizations/me", response_model=OrganizationSummary)
def update_my_organization(
    payload: OrganizationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationSummary:
    organization = _current_organization(current_user)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(organization, field, value)
    audit.record_audit(
        db,
        actor=current_user,
        action="organization.update_profile",
        entity_type="organization",
        entity_id=organization.id,
        details={"fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(organization)
    return OrganizationSummary.model_validate(organization)
