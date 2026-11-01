"""Curated, versioned smoke evaluation set for the Material Intelligence Engine.

Synthetic by design: it verifies the pipeline behaves as expected, not real
world accuracy. Without real labeled data, scientific quality metrics
(precision/recall on a representative corpus) are explicitly unavailable —
the API reports them as `null` with a disclaimer rather than inventing
labels (blueprint rule).
"""

from . import sbert, similarity
from .taxonomy import TAXONOMY_VERSION

EVAL_SET_VERSION = "material-eval-smoke-v1"

# (id, description, expected taxonomy type_id)
CASES: list[tuple[str, str, str]] = [
    ("copper-wire-01", "Clean copper wire scrap from motor rewinding", "metals.copper"),
    ("alu-extrusion-01", "Aluminium extrusion offcuts from window frames", "metals.aluminium"),
    ("ms-offcuts-01", "Mild steel offcuts from a fabrication line", "metals.mild_steel"),
    ("brass-turnings-01", "Brass turnings from CNC machining", "metals.brass"),
    ("pet-flakes-01", "Washed clear PET flakes from bottle bales", "plastics.pet_clear"),
    ("hdpe-drums-01", "Empty HDPE drums, rinsed, palletized", "plastics.polyethylene"),
    ("occ-bales-01", "Baled corrugated cardboard, clean and dry", "paper_cardboard.occ"),
    ("pallet-timber-01", "Damaged wooden pallets and timber offcuts", "wood.pallet_timber"),
    ("glass-cullet-01", "Clean flint glass cullet from bottling plant", "glass.cullet"),
    ("cotton-rags-01", "Cotton fabric offcuts from garment factory", "textiles.cotton"),
    ("pcb-scrap-01", "Populated circuit boards from IT asset disposal", "electronics.pcb"),
    ("used-oil-01", "Used hydraulic oil from plant maintenance", "chemicals.waste_oil"),
]

DISCLAIMER = (
    "Synthetic smoke set for pipeline verification only; not a measure of "
    "real-world accuracy. Scientific quality metrics are unavailable until a "
    "real labeled dataset is supplied."
)


def _method_name() -> str:
    return "sbert-cosine" if sbert.is_available() else "alias+tfidf"


def evaluate_smoke_set() -> dict:
    """Top-1 / top-3 accuracy of the pipeline over the smoke set.

    The alias path is exact by construction, so the smoke set primarily
    guards against taxonomy regressions and similarity-ranking breakage.
    """
    from .engine import suggest_material_attributes

    top1 = 0
    top3 = 0
    for _case_id, description, expected_type_id in CASES:
        result = suggest_material_attributes(description)
        value = result["suggestions"]["material_type"]["value"]
        predicted_ids = [value["type_id"]] if value else []
        if not predicted_ids:
            # fall back to full similarity ranking for top-3 stability
            predicted_ids = [entry.type_id for entry, _score in similarity.rank_types(description)[:3]]
        if predicted_ids and predicted_ids[0] == expected_type_id:
            top1 += 1
        if expected_type_id in predicted_ids[:3]:
            top3 += 1

    total = len(CASES)
    return {
        "eval_set": EVAL_SET_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "method": _method_name(),
        "size": total,
        "metrics": {
            "top1_accuracy": round(top1 / total, 4),
            "top3_accuracy": round(top3 / total, 4),
            # Real precision/recall would need a real labeled dataset:
            "precision_recall_on_real_data": None,
        },
        "disclaimer": DISCLAIMER,
    }
