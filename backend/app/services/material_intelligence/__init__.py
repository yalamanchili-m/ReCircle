"""Material Intelligence Engine package (blueprint Phase 4)."""

from .engine import suggest_material_attributes
from .evaluation import evaluate_smoke_set
from .taxonomy import TAXONOMY_VERSION

__all__ = ["TAXONOMY_VERSION", "evaluate_smoke_set", "suggest_material_attributes"]
