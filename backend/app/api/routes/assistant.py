"""AI Sustainability Assistant API (blueprint Phase 14).

`POST /api/assistant/ask` is the main endpoint: any signed-in user may ask;
tenant scoping happens before retrieval inside the engine. The evaluation
endpoint exposes the curated retrieval/abstention gate with explicit
synthetic-data disclaimers. Knowledge-source listing shows what the
assistant may cite, per user.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.models.assistant import KnowledgeChunk
from app.services import assistant
from app.services.assistant.engine import CAVEATS, QuestionValidationError

router = APIRouter()

MAX_QUESTION_CHARS = 1000


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)


@router.post("/assistant/ask")
def assistant_ask(
    payload: QuestionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieval-augmented answer with citations; never invents facts."""
    try:
        payload_out = assistant.ask(db, current_user, payload.question)
    except QuestionValidationError as error:
        db.commit()  # nothing to persist; keeps DB session clean
        raise HTTPException(status_code=422, detail=str(error))
    db.commit()
    return payload_out


@router.get("/assistant/sources")
def assistant_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Knowledge sources the assistant may use for this user, with counts."""
    counts = dict(
        db.execute(
            select(KnowledgeChunk.source_type, func.count())
            .where(KnowledgeChunk.is_active.is_(True))
            .group_by(KnowledgeChunk.source_type)
        ).all()
    )
    db.commit()
    return {
        "allowed_sources": [
            "curated platform method documents (trusted, reviewed)",
            "public regulation/news items (untrusted external text, always labeled)",
            "public active marketplace listings (all organizations)",
            "your own organization records (listings, requirements) — org-filtered before retrieval",
        ],
        "platform_chunk_counts": counts,
        "caveats": CAVEATS,
    }


@router.get("/assistant/evaluation")
def assistant_evaluation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Curated retrieval + abstention evaluation (synthetic set, honest gates)."""
    payload = assistant.run_evaluation(db, current_user)
    db.commit()
    return payload


@router.get("/assistant/runs")
def assistant_recent_runs(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """This user's own recent runs; admin sees all."""
    from app.models.assistant import AssistantRun

    query = (
        select(AssistantRun)
        .order_by(AssistantRun.created_at.desc())
        .limit(limit)
    )
    if current_user.role != "admin":
        query = query.where(AssistantRun.user_id == current_user.id)
    rows = db.scalars(query).all()
    db.commit()
    return {
        "runs": [
            {
                "id": str(run.id),
                "mode": run.mode,
                "question": run.question,
                "created_at": run.created_at.isoformat(),
                "runtime_ms": run.runtime_ms,
                "citation_count": len(run.citations or []),
            }
            for run in rows
        ]
    }
