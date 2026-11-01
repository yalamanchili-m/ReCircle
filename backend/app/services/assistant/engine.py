"""Assistant engine facade: permission-scoped retrieval + optional LLM.

Pipeline per question (all deterministic on the reading side):
1. Validate the question (bounded length, active user).
2. Refresh the platform corpus (idempotent sync, includes Phase 13 items).
3. Retrieve ONLY from knowledge this user may access - platform-scope chunks
   plus this organization's own records (org filter applied BEFORE scoring).
4. If no evidence passes the relevance gate: abstain honestly (never a
   hallucinated answer) - this is guaranteed in code even if the LLM is on.
5. Try an LLM answer with the strict evidence-only prompt. Any failure
   degrades to `retrieve_only` mode with the cited evidence.
6. Record the run (`assistant_runs`) in the caller's transaction.

Every response carries mode, answer, machine-readable citations, retrieval
stats, caveats, and version stamps so answers stay auditable.
"""

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User
from app.models.assistant import AssistantRun
from app.services.assistant import documents, generation, ingestion, retrieval

ASSISTANT_VERSION = "assistant-eng-v1"

CAVEATS = (
    "Answers are informational only: not legal advice, not a safety "
    "determination, and not a substitute for reviewing the underlying record.",
    "Evidence quoted from regulation/news items is untrusted public text and "
    "is labeled `untrusted: true` in citations.",
    "If the answer mode is `retrieve_only` or `abstained`, no language-model "
    "text is present in this response.",
)

QUESTION_MIN_CHARS = 3
QUESTION_MAX_CHARS = 1000


class QuestionValidationError(ValueError):
    pass


def _user_scope(user: User) -> tuple:
    """The ONLY org id allowed in retrieval for this user (privacy gate)."""
    org_id = user.organization_id if hasattr(user, "organization_id") else (
        user.organization.id if user.organization else None
    )
    return org_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ask(
    db: Session,
    user: User,
    question: str,
    *,
    call_llm=None,
) -> dict:
    started = time.monotonic()
    text = (question or "").strip()
    if len(text) < QUESTION_MIN_CHARS:
        raise QuestionValidationError(
            f"question is too short (minimum {QUESTION_MIN_CHARS} characters)"
        )
    if len(text) > QUESTION_MAX_CHARS:
        raise QuestionValidationError(
            f"question is too long (maximum {QUESTION_MAX_CHARS} characters)"
        )

    sync = ingestion.sync_knowledge(db)
    org_id = _user_scope(user)
    # Privacy: retrieval sees only platform chunks + this org's records.
    evidence = retrieval.retrieve(db, text, org_id)

    base_stats = {
        "allowed_chunks": sync["active_chunks"],
        "evidence_count": len(evidence),
        "organization_id": str(org_id) if org_id else None,
    }
    run_kwargs = {
        "user_id": user.id,
        "organization_id": org_id,
        "question": text,
    }
    citation_ordinal = 1
    citations = []
    evidence_texts = []
    for item in evidence:
        citations.append(item.as_citation(citation_ordinal))
        evidence_texts.append(f'[citation {citation_ordinal}] {item.title}\n{item.content}')
        citation_ordinal += 1
    retrieval_stats = {
        **base_stats,
        "top_scores": [
            {"evidence_key": item.key, "score": item.score, "kind": item.kind}
            for item in evidence
        ],
        "retrieval_version": retrieval.RETRIEVAL_VERSION,
    }

    mode = "abstained"
    answer: str | None = None
    model_name = None
    error = None

    if not evidence:
        answer = (
            "I could not find relevant evidence among the platform documents, "
            "regulation/news items, and records your organization may access. "
            "Please rephrase the question or review the related records first. "
            "No answer was invented."
        )
    else:
        try:
            raw = generation.generate_answer(text, evidence_texts, call_llm=call_llm)
            model_name = get_settings().ollama_model
            if generation.is_abstention(raw):
                mode = "abstained"
                answer = raw
            else:
                mode = "generated"
                answer = raw
        except generation.GenerationUnavailableError as llm_error:
            mode = "retrieve_only"
            error = str(llm_error)
            answer = (
                "The language model is unavailable, so here is the retrieved "
                "evidence instead (no model-generated text): "
                + "; ".join(
                    f"[{c['n']}] {c['title']}" for c in citations
                )
            )
            model_name = None

    run = AssistantRun(
        mode=mode,
        answer=answer,
        citations=citations,
        retrieval_stats=retrieval_stats,
        error=error,
        retrieval_version=retrieval.RETRIEVAL_VERSION,
        prompt_version=generation.PROMPT_VERSION,
        model_name=model_name,
        runtime_ms=int((time.monotonic() - started) * 1000),
        **run_kwargs,
    )
    db.add(run)
    db.flush()

    return {
        "run_id": str(run.id),
        "mode": mode,
        "answer": answer,
        "citations": citations,
        "retrieval_stats": retrieval_stats,
        "caveats": CAVEATS,
        "versions": {
            "engine": ASSISTANT_VERSION,
            "ingestion": ingestion.INGESTION_VERSION,
            "documents": documents.DOCUMENTS_VERSION,
            "retrieval": retrieval.RETRIEVAL_VERSION,
            "prompt": generation.PROMPT_VERSION,
            "model_name": model_name,
        },
        "runtime_ms": run.runtime_ms,
        "generated_at": _now_iso(),
    }
