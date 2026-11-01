"""AI Sustainability Assistant service package (blueprint Phase 14, RAG)."""

from __future__ import annotations

from app.services.assistant.engine import ask
from app.services.assistant.evaluation import run_evaluation
from app.services.assistant.generation import GENERATION_UNAVAILABLE
from app.services.assistant.ingestion import sync_knowledge
from app.services.assistant.retrieval import retrieve

__all__ = [
    "GENERATION_UNAVAILABLE",
    "ask",
    "retrieve",
    "run_evaluation",
    "sync_knowledge",
]
