"""Pure-Python TF-IDF + cosine similarity baseline.

No external dependencies and no network access: this is the deterministic
fallback used whenever Sentence-BERT is disabled or unavailable.
"""

import math
import re

from .taxonomy import MaterialType, all_types

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def _document_text(entry: MaterialType) -> str:
    return " ".join(
        [entry.label, entry.description, entry.category]
        + entry.aliases
        + entry.applications
        + entry.industries
    )


def _term_frequencies(tokens: list[str]) -> dict[str, float]:
    frequencies: dict[str, float] = {}
    for token in tokens:
        frequencies[token] = frequencies.get(token, 0.0) + 1.0
    return frequencies


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class TfidfIndex:
    """TF-IDF vectors over the taxonomy corpus, precomputed once per process."""

    def __init__(self) -> None:
        self._documents: list[dict[str, float]] = []
        self._entries: list[MaterialType] = []
        self._build()

    def _build(self) -> None:
        tokenized_docs = [tokenize(_document_text(entry)) for entry in all_types()]
        document_frequency: dict[str, int] = {}
        for tokens in tokenized_docs:
            for term in set(tokens):
                document_frequency[term] = document_frequency.get(term, 0) + 1

        total_documents = len(tokenized_docs)
        vectors: list[dict[str, float]] = []
        for tokens in tokenized_docs:
            frequencies = _term_frequencies(tokens)
            vector = {
                term: count * math.log(total_documents / document_frequency[term] + 1.0)
                for term, count in frequencies.items()
            }
            vectors.append(vector)

        self._entries = all_types()
        self._documents = vectors

    def scores(self, query: str) -> list[tuple[MaterialType, float]]:
        """Cosine similarity of the query against every taxonomy entry."""
        query_vector = _term_frequencies(tokenize(query))
        results = [
            (entry, _cosine(query_vector, document))
            for entry, document in zip(self._entries, self._documents)
        ]
        results.sort(key=lambda pair: (-pair[1], pair[0].type_id))
        return results


_index: TfidfIndex | None = None


def get_index() -> TfidfIndex:
    global _index
    if _index is None:
        _index = TfidfIndex()
    return _index


def rank_types(query: str) -> list[tuple[MaterialType, float]]:
    return get_index().scores(query)
