"""Curated (trusted) knowledge documents + shared chunking utilities.

Allowed knowledge sources for the assistant (blueprint Phase 14):
1. Curated method/limitation documents maintained in code (trusted; reviewed
   content explaining how platform estimates and scores are produced).
2. Regulation/news items already ingested by Phase 13 (platform-readable
   content; UNTRUSTED external text - always rendered as data in prompts).
3. Live PostgreSQL records the requesting user's organization may access
   (own-org private records + public active marketplace listings), resolved
   at question time with org filters applied BEFORE retrieval.

Chunking overlaps slightly so documents split across windows stay findable
by lexical search. Documents here are factual platform documentation only -
never invented third-party claims.
"""

import hashlib

CHUNK_SIZE = 600
CHUNK_OVERLAP = 120

DOCUMENTS_VERSION = "assistant-method-docs-v1"


def _md(title: str, content: str) -> dict:
    return {"title": title, "content": content}


def method_documents() -> list[dict]:
    """Trusted platform documents explaining methods and limitations."""
    return [
        _md(
            "Carbon impact estimation method (differential factor arithmetic)",
            (
                "ReCircle estimates avoided emissions per recovery record with "
                "differential arithmetic: avoided CO2e = (landfill baseline intensity - chosen "
                "recovery-route intensity) x recovered tonnes. The landfill "
                "route is the baseline and contributes zero by construction, so "
                "estimates are never negative credits. Factors come from the "
                "versioned factor catalog factor-catalog-v2-differential, which "
                "holds curated approximation rows pending real EPA WARM v15 "
                "ingestion; the exact catalog version is recorded on every "
                "estimate. Unsupported combinations (no curated factor for a "
                "route or category) are marked unsupported with explicit "
                "reasons instead of zero values. Every estimate also shows a "
                "worst-case uncertainty interval, and estimates are always "
                "distinguished from user-reported or verified outcomes."
            ),
        ),
        _md(
            "Buyer matching method and decision-support limits",
            (
                "The Circular Match Engine ranks listings against a buyer "
                "requirement with a deterministic weighted baseline: category "
                "40, quantity 25, quality 20, location 10, price 5, with "
                "inapplicable criteria dropped and weights renormalized. "
                "Hard constraints (category mismatch, inactive listings, "
                "non-positive quantities, over-budget prices) exclude "
                "candidates entirely before ranking. A content-based material "
                "fit score compares normalized material text, optionally "
                "re-ranked by a KNN-style scoring pass. Matching output is "
                "decision support only: it is NOT proof of chemical, legal, or "
                "process safety, and every candidate ships a score breakdown "
                "with reasons and warnings."
            ),
        ),
        _md(
            "ESG metric states: user-reported vs estimated vs verified",
            (
                "ESG metrics reconcile to source records. Recovered quantity "
                "is user-reported. Landfill diversion and avoided emissions "
                "are factor-based estimates marked with the factor catalog "
                "version; they are never presented as verified outcomes. "
                "Verified status comes only from admin verification of a "
                "recovery record. Aggregation per recovery record uses only "
                "current impact estimates (a partial unique index enforces one "
                "current row), which prevents double counting across listings, "
                "matches, and transactions."
            ),
        ),
        _md(
            "Regulation and news summaries are informational, not legal advice",
            (
                "The Regulation-News aggregator displays items from curated "
                "public sources with the original link preserved. Short "
                "summaries are either automated extractions of the "
                "publisher's own text or clearly AI-generated summaries. "
                "Neither kind is legal advice or authoritative compliance "
                "guidance: the linked original source is always authoritative, "
                "and compliance decisions require qualified human review of "
                "the original text."
            ),
        ),
        _md(
            "Pathway scoring model (Weighted Sum Model)",
            (
                "The Circular Path Optimizer compares reuse, recycle, upcycle, "
                "and remanufacture pathways with a Weighted Sum Model over "
                "normalized criteria: carbon impact, distance, cost, demand, "
                "and feasibility. Each criterion states whether it is "
                "minimized or maximized and carries a documented weight. "
                "Feasibility gates run before ranking, so hard safety or "
                "regulatory constraints can never be overridden by scores. "
                "Missing criteria are dropped with weight renormalization, and "
                "a sensitivity check reports how stable the ranking is. "
                "Chemical listings are hard-gated to recycling only."
            ),
        ),
        _md(
            "How the assistant works and its limits",
            (
                "This assistant is a retrieval-augmented question-answering "
                "service. It first searches only knowledge the requesting "
                "user is allowed to see: curated platform method documents, "
                "public regulation/news items, active public marketplace "
                "listings, and the user's own organization records. If the "
                "retrieved evidence is insufficient, the assistant says so "
                "instead of inventing facts. Answers cite their sources and "
                "are informational only: they are not legal advice, not a "
                "safety determination, and not a substitute for reviewing the "
                "underlying record. Text quoted from external regulation items "
                "is untrusted data and is never treated as instructions."
            ),
        ),
    ]


def chunk_text(content: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split long text into overlapping windows on sentence boundaries.

    Deterministic: fixed sizes, pure string ops, no RNG. Short documents are
    returned as a single chunk unchanged.
    """
    text = " ".join(content.split())
    if len(text) <= size:
        return [text]
    # Prefer sentence boundaries when they exist inside the window.
    sentences = [s.strip() for s in text.replace("?", ".").replace("!", ".").split(". ") if s.strip()]
    rebuilt: list[str] = []
    current = ""
    for sentence in sentences:
        suffix = "" if not sentence.endswith(".") else "."
        piece = (current + " " + sentence).strip()
        if len(piece) > size and current:
            rebuilt.append(current)
            current = sentence + suffix
        else:
            current = piece + suffix
    if current:
        rebuilt.append(current)
    # Merge any sentence fragments that are still longer than size.
    chunks: list[str] = []
    for part in rebuilt:
        part = part.strip()
        if len(part) <= size:
            if chunks and len(part) < overlap:
                chunks[-1] = (chunks[-1] + " " + part).strip()
            else:
                chunks.append(part)
            continue
        start = 0
        while start < len(part):
            chunks.append(part[start : start + size].strip())
            start += max(1, size - overlap)
    return chunks


def content_hash_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
