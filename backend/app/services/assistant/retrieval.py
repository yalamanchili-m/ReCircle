"""Lexical retrieval for the assistant (blueprint Phase 14).

Design decisions:
- Retrieval starts lexical: TF-IDF cosine over the question vs. candidate
  texts, rebuilt per query over the (bounded) allowed corpus. This is the
  deterministic, offline baseline; embeddings are opt-in and only added when
  meaningfully evaluated (same policy as the Material Intelligence engine).
- Tenant permissions are enforced BEFORE any scoring happens: the candidate
  set is assembled in `engine.py` from (a) active platform-scope chunks and
  (b) live PostgreSQL records that the requesting user's organization may
  access. Retrieval itself never sees rows outside that filtered set.
- Insufficient evidence triggers abstention (`MIN_EVIDENCE_SCORE`).
"""

import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assistant import KnowledgeChunk
from app.models.material_requirement import MaterialRequirement
from app.models.waste_listing import WasteListing

RETRIEVAL_VERSION = "assistant-retrieval-v1"

# Below this cosine score evidence is considered not relevant enough to cite.
MIN_EVIDENCE_SCORE = 0.08
MAX_CITATIONS = 6

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from how i in is it of on or that the this to "
    "was what when where which who why will with you your do does".split()
)


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _STOPWORDS
    ]


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(w * right.get(t, 0.0) for t, w in left.items())
    left_norm = math.sqrt(sum(w * w for w in left.values()))
    right_norm = math.sqrt(sum(w * w for w in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    frequencies: dict[str, int] = {}
    for token in tokens:
        frequencies[token] = frequencies.get(token, 0) + 1
    return {
        token: count * idf.get(token, 1.0) for token, count in frequencies.items()
    }


class Evidence:
    """One retrievable candidate: chunk row or a live org/DB record."""

    __slots__ = ("key", "kind", "title", "content", "score", "citation")

    def __init__(
        self, key: str, kind: str, title: str, content: str, citation: dict | None = None
    ) -> None:
        self.key = key
        self.kind = kind
        self.title = title
        self.content = content
        self.score = 0.0
        self.citation = citation

    def as_citation(self, ordinal: int) -> dict:
        basis = self.citation or {}
        return {
            "n": ordinal,
            "evidence_key": self.key,
            "kind": self.kind,
            "title": self.title,
            "excerpt": self.content[:280],
            "url": basis.get("url"),
            "source_label": basis.get("source_label"),
            "record_id": basis.get("record_id"),
            "untrusted": basis.get("untrusted", False),
        }


def load_platform_chunks(db: Session) -> list[Evidence]:
    chunks = db.scalars(
        select(KnowledgeChunk).where(
            KnowledgeChunk.is_active.is_(True),
            KnowledgeChunk.access_scope == "platform",
        )
    ).all()
    trust_labels = {
        "method_document": ("Curated platform document", False),
        "platform_note": ("Platform note", False),
        "regulation_item": ("Regulation/news item (public, untrusted source text)", True),
    }
    return [
        Evidence(
            key=chunk.chunk_key,
            kind=chunk.source_type,
            title=chunk.title,
            content=chunk.content,
            citation={
                "url": None,
                "source_label": trust_labels[chunk.source_type][0],
                "record_id": chunk.source_ref_id,
                "untrusted": trust_labels[chunk.source_type][1],
            },
        )
        for chunk in chunks
    ]


def load_org_records(db: Session, organization_id) -> list[Evidence]:
    """Live org record candidates. ALWAYS org-filtered - never other tenants."""
    if organization_id is None:
        return []
    evidence: list[Evidence] = []
    listings = db.scalars(
        select(WasteListing).where(WasteListing.organization_id == organization_id)
    ).all()
    for listing in listings:
        body = " ".join(
            filter(
                None,
                [
                    listing.title,
                    listing.description,
                    listing.material_name,
                    listing.composition,
                    listing.category,
                    listing.status,
                    listing.city,
                    str(listing.region or ""),
                ],
            )
        )
        # Non-listed drafts stay usable for their own org but are labeled so
        # answers can distinguish visibility.
        visible = "marketplace-visible (active)" if listing.status == "active" else (
            "organization-only (not public)"
        )
        evidence.append(
            Evidence(
                key=f"listing:{listing.id}",
                kind="listing",
                title=listing.title,
                content=f"{body} [{visible}]",
                citation={
                    "url": f"/marketplace/{listing.id}" if listing.status == "active" else None,
                    "source_label": f"Own listing ({visible})",
                    "record_id": str(listing.id),
                    "untrusted": False,
                },
            )
        )
    requirements = db.scalars(
        select(MaterialRequirement).where(
            MaterialRequirement.organization_id == organization_id
        )
    ).all()
    for requirement in requirements:
        body = " ".join(
            filter(
                None,
                [
                    requirement.title,
                    getattr(requirement, "description", None),
                    getattr(requirement, "category", None),
                    requirement.status,
                ],
            )
        )
        evidence.append(
            Evidence(
                key=f"requirement:{requirement.id}",
                kind="requirement",
                title=requirement.title,
                content=body,
                citation={
                    "url": None,
                    "source_label": "Own buyer requirement (organization-only)",
                    "record_id": str(requirement.id),
                    "untrusted": False,
                },
            )
        )
    return evidence


def score_evidence(question: str, evidence: list[Evidence]) -> list[Evidence]:
    """TF-IDF cosine rerank of the allowed candidate set (deterministic)."""
    corpus_tokens = [tokenize(item.content) for item in evidence]
    document_frequency: dict[str, int] = {}
    for tokens in corpus_tokens:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    total = len(corpus_tokens) or 1
    idf = {term: math.log(total / freq + 1.0) for term, freq in document_frequency.items()}
    query_vector = _tfidf_vector(tokenize(question), idf)
    for item, tokens in zip(evidence, corpus_tokens):
        item.score = round(_cosine(query_vector, _tfidf_vector(tokens, idf)), 6)
    evidence.sort(key=lambda item: (-item.score, item.key))
    return [item for item in evidence if item.score >= MIN_EVIDENCE_SCORE][:MAX_CITATIONS]


def retrieve(db: Session, question: str, organization_id) -> list[Evidence]:
    """Full retrieval: platform chunks + THIS org's records only, then rank."""
    candidates = load_platform_chunks(db) + load_org_records(db, organization_id)
    return score_evidence(question, candidates)
