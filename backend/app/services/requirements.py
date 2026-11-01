from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MaterialRequirement, User
from app.schemas.requirement import RequirementCreate, RequirementUpdate


def get_requirement_or_404(db: Session, requirement_id: UUID) -> MaterialRequirement:
    requirement = db.get(MaterialRequirement, requirement_id)
    if requirement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found"
        )
    return requirement


def assert_can_manage(requirement: MaterialRequirement, user: User) -> None:
    if user.role == "admin":
        return
    if user.organization_id is None or requirement.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner organization may manage this requirement",
        )


def list_requirements(
    db: Session,
    user: User,
    requirement_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MaterialRequirement], int]:
    query = select(MaterialRequirement)
    if not (user.role == "admin" and user.organization_id is None):
        query = query.where(MaterialRequirement.organization_id == user.organization_id)
    if requirement_status:
        query = query.where(MaterialRequirement.status == requirement_status)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(MaterialRequirement.created_at.desc(), MaterialRequirement.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def create_requirement(
    db: Session, data: RequirementCreate, user: User
) -> MaterialRequirement:
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="User has no organization; cannot create requirements",
        )
    requirement = MaterialRequirement(
        **data.model_dump(),
        organization_id=user.organization_id,
        created_by=user.id,
        status="active",
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement


def update_requirement(
    db: Session, requirement: MaterialRequirement, data: RequirementUpdate
) -> MaterialRequirement:
    updates = data.model_dump(exclude_unset=True)
    if updates:
        for field_name, value in updates.items():
            setattr(requirement, field_name, value)
        db.commit()
        db.refresh(requirement)
    return requirement
