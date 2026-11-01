"""Material Intelligence suggestion pipeline (blueprint Phase 4).

Produces reviewable, normalized attribute suggestions with per-field
provenance, confidence, evidence, and a model version. Suggestions are
advisory only: they never become confirmed attributes until a user reviews,
edits, and accepts them. The pipeline is deterministic and fully offline —
Sentence-BERT is opt-in and falls back to TF-IDF when unavailable.
"""

from dataclasses import dataclass

from app.core.constants import MATERIAL_CATEGORIES

from . import sbert, similarity
from .taxonomy import (
    CATEGORY_PATHWAY_DEFAULTS,
    TAXONOMY_VERSION,
    MaterialType,
    normalize_label,
    resolve_by_alias,
)

ENGINE_VERSION = "material-intel-v1"

# Below this cosine score a taxonomy match is treated as "no confident
# match" and reported as unverified instead of guessing.
MIN_SIMILARITY_CONFIDENCE = 0.05


@dataclass
class Suggestion:
    value: object
    provenance: str
    confidence: float
    evidence: dict


def _confidence_from_similarity(score: float) -> float:
    """Map a cosine score in [0, 1] onto a conservative confidence in [0, 1]."""
    return round(min(1.0, max(0.0, score)), 4)


def suggest_material_attributes(description: str) -> dict:
    """Build normalized suggestions for a material description.

    Returns a dict (JSON-serializable) with:
    - suggestions: per-field {value, provenance, confidence, evidence}
    - original_label: the input text, always preserved
    - missing_information, needs_review, model/method/taxonomy versions
    """
    text = description.strip()
    original_label = normalize_label(text)

    alias_match = resolve_by_alias(text)
    tfidf_scores = similarity.rank_types(text)
    tfidf_best_type, tfidf_best_score = tfidf_scores[0] if tfidf_scores else (None, 0.0)

    use_sbert = sbert.is_available()
    if use_sbert:
        # Embedding similarity over the same corpus; method is reported.
        from .taxonomy import all_types

        corpus = [f"{entry.label}. {entry.description}" for entry in all_types()]
        embeddings = sbert.embed([text] + corpus)
        if embeddings is not None:
            query = embeddings[0]
            candidates = []
            for entry, vector in zip(all_types(), embeddings[1:]):
                score = sum(a * b for a, b in zip(query, vector))
                candidates.append((entry, score))
            candidates.sort(key=lambda pair: (-pair[1], pair[0].type_id))
            best_type, best_score = candidates[0] if candidates else (tfidf_best_type, tfidf_best_score)
            method = "sbert-cosine"
        else:  # pragma: no cover - only when encoding fails
            best_type, best_score, method = tfidf_best_type, tfidf_best_score, "alias+tfidf"
    else:
        best_type, best_score, method = tfidf_best_type, tfidf_best_score, "alias+tfidf"

    # Alias matches are exact-evidence and outrank pure similarity guesses.
    if alias_match is not None:
        matched_type, matched_alias = alias_match
        material_suggestion = Suggestion(
            value={"type_id": matched_type.type_id, "label": matched_type.label},
            provenance="ai_inferred",
            confidence=1.0,
            evidence={
                "source": "taxonomy_alias",
                "matched_alias": matched_alias,
                "original_label": original_label,
            },
        )
        category_value = matched_type.category
        category_evidence = {
            "source": "taxonomy_alias",
            "matched_alias": matched_alias,
            "type_id": matched_type.type_id,
        }
        applications = matched_type.applications
        industries = matched_type.industries
    elif best_type is not None and _confidence_from_similarity(best_score) >= MIN_SIMILARITY_CONFIDENCE:
        matched_type = best_type
        material_suggestion = Suggestion(
            value={"type_id": best_type.type_id, "label": best_type.label},
            provenance="ai_inferred",
            confidence=_confidence_from_similarity(best_score),
            evidence={
                "source": f"{method}_similarity",
                "original_label": original_label,
            },
        )
        category_value = best_type.category
        category_evidence = {
            "source": f"{method}_similarity",
            "type_id": best_type.type_id,
        }
        applications = best_type.applications
        industries = best_type.industries
    else:
        matched_type = None
        material_suggestion = Suggestion(
            value=None,
            provenance="unverified",
            confidence=0.0,
            evidence={"source": "no_match", "original_label": original_label},
        )
        category_value = None
        category_evidence = {"source": "no_match"}
        applications = []
        industries = []

    suggestions: dict = {
        "material_type": {
            "value": material_suggestion.value,
            "provenance": material_suggestion.provenance,
            "confidence": material_suggestion.confidence,
            "evidence": material_suggestion.evidence,
        },
        "category": {
            "value": category_value,
            "provenance": "ai_inferred" if category_value else "unverified",
            "confidence": material_suggestion.confidence,
            "evidence": category_evidence,
        },
        "possible_applications": {
            "value": applications,
            "provenance": "ai_inferred" if applications else "unverified",
            "confidence": material_suggestion.confidence,
            "evidence": {"source": "taxonomy", "type_id": matched_type.type_id if matched_type else None},
        },
        "suitable_industries": {
            "value": industries,
            "provenance": "ai_inferred" if industries else "unverified",
            "confidence": material_suggestion.confidence,
            "evidence": {"source": "taxonomy", "type_id": matched_type.type_id if matched_type else None},
        },
        "candidate_pathways": {
            "value": CATEGORY_PATHWAY_DEFAULTS.get(category_value, [])
            if category_value
            else [],
            "provenance": "source_derived" if category_value else "unverified",
            "confidence": None,
            "evidence": {
                "source": "category_pathway_mapping",
                "taxonomy_version": TAXONOMY_VERSION,
            },
        },
    }

    missing: list[str] = []
    if category_value is None:
        missing.append("material category")
    missing.append("quantity and unit")
    missing.append("location (city/region)")

    return {
        "suggestions": suggestions,
        "original_label": original_label,
        "missing_information": missing,
        "needs_review": True,
        "model_version": ENGINE_VERSION,
        "method": method,
        "taxonomy_version": TAXONOMY_VERSION,
        "disclaimer": (
            "AI-inferred suggestions for review only; they are not laboratory-verified "
            "facts. Category must be one of: " + ", ".join(MATERIAL_CATEGORIES)
        ),
    }
