"""Audit event recording for sensitive actions.

Audit rows are written in the same database transaction as the action
itself, so an action is never persisted without its audit trail. Details
must never contain secrets or credentials.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor is not None else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
    db.flush()
