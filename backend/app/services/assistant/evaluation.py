"""Deterministic evaluation of retrieval + abstention (assessment fixture set).

The set is SYNTHETIC and version-controlled: it evaluates whether lexical
retrieval returns the right evidence among the curated corpus, and whether
genuinely unsupported questions trigger abstention. Real-data quality
metrics are explicitly unavailable until real labeled questions exist
(blueprint rule: never invent labels, never claim real-world accuracy).
"""

from sqlalchemy.orm import Session

from app.models import User
from app.services.assistant import documents, retrieval

EVALUATION_VERSION = "assistant-eval-v1"

# (question, expected evidence kind, expected key substring or None)
_EXPECTATIONS: list[dict] = [
    {
        "question": "How are avoided emissions estimated on the platform?",
        "expect": "contains:doc:",
        "note": "method document on differential factor arithmetic",
    },
    {
        "question": "Is the buyer match score a safety certification?",
        "expect": "contains:doc:",
        "note": "matching method + decision-support limits document",
    },
    {
        "question": "What distinguishes verified from estimated ESG metrics?",
        "expect": "contains:doc:",
        "note": "ESG metric states document",
    },
    {
        "question": "Can I treat regulation summaries as legal advice?",
        "expect": "abstain_no",
        "note": "gate keeper: matching doc should surface and answer is guarded",
    },
    {
        "question": "How does the pathway optimizer score feasibility?",
        "expect": "contains:doc:",
        "note": "WSM document",
    },
    {
        "question": "What is the molar mass ofmodxneon?",
        "expect": "abstain",
        "note": "nonsense question must abstain",
    },
]


def _expectation_satisfied(question: str, results: list[retrieval.Evidence]) -> dict:
    spec = next(entry for entry in _EXPECTATIONS if entry["question"] == question)
    matched = [{"evidence_key": item.key, "kind": item.kind, "score": item.score} for item in results]
    if spec["expect"] == "abstain":
        satisfied = len(results) == 0
    elif spec["expect"] == "abstain_no":
        satisfied = len(results) > 0
    elif spec["expect"].startswith("contains:"):
        prefix = spec["expect"].split("contains:", 1)[1]
        satisfied = any(result.key.startswith(prefix) for result in results)
    else:  # pragma: no cover - defensive
        satisfied = False
    return {"satisfied": satisfied, "matches": matched}


def run_evaluation(db: Session, current_user: User | None = None) -> dict:
    """Run the curated evaluation set synchronously (small, bounded)."""
    cases = []
    passed = 0
    for spec in _EXPECTATIONS:
        results = retrieval.retrieve(
            db, spec["question"], organization_id=None
        )
        check = _expectation_satisfied(spec["question"], results)
        passed += int(check["satisfied"])
        cases.append(
            {
                "question": spec["question"],
                "note": spec["note"],
                "passed": check["satisfied"],
                "top_matches": check["matches"][:3],
            }
        )
    return {
        "evaluation_version": EVALUATION_VERSION,
        "documents_version": documents.DOCUMENTS_VERSION,
        "retrieval_version": retrieval.RETRIEVAL_VERSION,
        "case_count": len(_EXPECTATIONS),
        "passed": passed,
        "cases": cases,
        "limitations": (
            "Synthetic evaluation set; retrieval-quality metrics on real user "
            "questions are unavailable until real labeled data is supplied. "
            "No generated-answer quality is claimed: the LLM path is optional "
            "and evaluated separately when configured."
        ),
        "real_data_metrics": None,
    }
