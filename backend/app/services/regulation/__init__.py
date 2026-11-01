"""Regulation-News Aggregator service package (blueprint Phase 13)."""

from app.services.regulation.ingest import refresh, summarize
from app.services.regulation.sources import (
    SOURCE_REGISTRY_VERSION,
    ensure_sources,
    sources_payload,
)

__all__ = [
    "SOURCE_REGISTRY_VERSION",
    "ensure_sources",
    "refresh",
    "sources_payload",
    "summarize",
]
