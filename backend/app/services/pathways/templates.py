"""Versioned circular pathway templates and feasibility rules (Phase 8).

Curated, deterministic, no network. Four required pathway types — reuse,
recycle, upcycle, remanufacture — with steps, required processing, transport
assumptions, and per-category feasibility rules. Hard safety constraints
(e.g. contaminated chemicals) live here and can never be overridden by
scores.
"""

PATHWAY_TEMPLATES_VERSION = "pathway-templates-v1"

REQUIRED_PROCESSING = {
    "reuse": ["collection", "inspection", "cleaning", "redistribution"],
    "recycle": ["collection", "sorting", "material_recovery_processing"],
    "upcycle": ["collection", "quality_assessment", "transformation_processing"],
    "remanufacture": ["collection", "disassembly", "part_inspection", "reassembly", "testing"],
}

# Transport legs assumed per pathway (drives the distance criterion).
TRANSPORT_LEGS = {
    "reuse": 1,
    "recycle": 2,
    "upcycle": 2,
    "remanufacture": 3,
}

# Curated relative environmental prior (0-1, higher = less processing
# intensity / better expected circular outcome). This is an ordering prior
# from circular-economy practice — NOT measured carbon data. Absolute
# environmental impact becomes available only after EPA WARM factors are
# ingested (Phase 9).
ENVIRONMENTAL_PRIOR = {
    "reuse": 0.9,
    "remanufacture": 0.8,
    "recycle": 0.7,
    "upcycle": 0.6,
}

# Processing intensity multipliers used to derive a relative cost proxy from
# the listing price (curated assumptions, not measured costs).
COST_MULTIPLIER = {
    "reuse": 0.2,
    "recycle": 0.5,
    "upcycle": 0.8,
    "remanufacture": 0.9,
}

# Contamination penalty per pathway when contamination_notes is present
# (cleaner-input pathways are penalized harder).
CONTAMINATION_PENALTY = {
    "reuse": 0.3,
    "upcycle": 0.3,
    "remanufacture": 0.3,
    "recycle": 0.15,
}

# Hard feasibility rules per pathway/category. Categories not listed are
# feasible for that pathway.
INFEASIBLE_CATEGORIES = {
    # Safety rule: chemicals cannot be "reused" as-is without re-refining
    # (which is a recycling pathway in the taxonomy).
    "reuse": {"chemicals"},
    # Remanufacture requires discrete, part-recoverable goods.
    "remanufacture": {"metals", "plastics", "paper_cardboard", "glass",
                      "textiles", "organics", "chemicals"},
    # Upcycling requires processable or transformable material; raw chemicals
    # are excluded for safety.
    "upcycle": {"chemicals"},
    "recycle": set(),
}

PATHWAY_LABELS = {
    "reuse": "Reuse",
    "recycle": "Recycle",
    "upcycle": "Upcycle",
    "remanufacture": "Remanufacture",
}


def all_pathway_ids() -> list[str]:
    return ["reuse", "recycle", "upcycle", "remanufacture"]


def is_feasible(pathway_id: str, category: str, contamination_notes: str | None) -> tuple[bool, str | None]:
    """Hard feasibility gate. Returns (feasible, reason)."""
    if pathway_id not in TRANSPORT_LEGS:
        return False, f"Unknown pathway '{pathway_id}'"
    if category in INFEASIBLE_CATEGORIES.get(pathway_id, set()):
        return False, (
            f"{PATHWAY_LABELS[pathway_id]} is not feasible for category "
            f"'{category}' under curated safety/processing rules"
        )
    if contamination_notes and pathway_id in ("reuse", "upcycle", "remanufacture"):
        # Contaminated streams can still enter these pathways only after
        # extra processing — downgraded, not excluded (recycling accepts
        # contamination with sorting).
        pass
    return True, None
