"""Opt-in Sentence-BERT adapter for semantic similarity.

Used only for embedding-based similarity over the taxonomy corpus — never as
a classifier (a generic embedding model is not a trained classifier). The
package and model weights are expected to be installed locally; when they are
missing the adapter reports itself unavailable and the engine falls back to
the TF-IDF baseline. No downloads are triggered at request time.
"""

import logging

from app.core.config import get_settings

logger = logging.getLogger("app.material_intelligence")

_state: dict[str, object] = {"checked": False, "model": None}


def _load_model():
    settings = get_settings()
    if not settings.sbert_enabled:
        return None
    if _state["checked"]:
        return _state["model"]
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _state["model"] = SentenceTransformer(settings.sbert_model_name)
    except Exception as exc:  # ImportError, model download errors, etc.
        logger.info("Sentence-BERT unavailable (%s); using TF-IDF baseline", exc)
        _state["model"] = None
    _state["checked"] = True
    return _state["model"]


def is_available() -> bool:
    return _load_model() is not None


def embed(texts: list[str]) -> list[list[float]] | None:
    model = _load_model()
    if model is None:
        return None
    embeddings = model.encode(texts, normalize_embeddings=True)
    return [list(map(float, vector)) for vector in embeddings]
