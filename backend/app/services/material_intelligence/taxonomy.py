"""Canonical, versioned material taxonomy with aliases.

Deterministic, pure-Python, no network. The taxonomy version is stamped on
every suggestion so changes are traceable. Original user labels are always
preserved alongside the canonical type.
"""

TAXONOMY_VERSION = "recircle-taxonomy-v1"

CATEGORY_PATHWAY_DEFAULTS = {
    "metals": ["reuse", "recycle"],
    "plastics": ["recycle"],
    "paper_cardboard": ["recycle"],
    "wood": ["reuse", "recycle", "biomass_recovery"],
    "glass": ["recycle"],
    "textiles": ["reuse", "recycle"],
    "organics": ["composting", "biogas"],
    "electronics": ["recycle", "precious_metal_recovery"],
    "chemicals": ["re-refining", "recovery"],
}


class MaterialType:
    def __init__(
        self,
        type_id: str,
        label: str,
        category: str,
        aliases: list[str],
        description: str,
        applications: list[str],
        industries: list[str],
    ):
        self.type_id = type_id
        self.label = label
        self.category = category
        self.aliases = aliases
        self.description = description
        self.applications = applications
        self.industries = industries


MATERIAL_TYPES: list[MaterialType] = [
    MaterialType(
        "metals.copper",
        "Copper scrap",
        "metals",
        ["copper", "copper wire", "cu scrap", "copper scrap"],
        "Copper scrap including wire, windings, and bus bar; high conductivity remelt feedstock.",
        ["cable manufacturing", "conductive fillers", "electrical components"],
        ["electrical equipment", "construction", "wire drawing"],
    ),
    MaterialType(
        "metals.aluminium",
        "Aluminium scrap",
        "metals",
        ["aluminium", "aluminum", "alu extrusion", "aluminium extrusion", "aluminium scrap"],
        "Aluminium scrap from extrusion, sheet, or castings; remelts at low energy cost.",
        ["extrusion billet", "die casting", "sheet rolling"],
        ["construction", "automotive", "packaging"],
    ),
    MaterialType(
        "metals.mild_steel",
        "Mild steel scrap",
        "metals",
        ["mild steel", "ms scrap", "steel offcuts", "steel scrap", "steel"],
        "Mild steel offcuts and scrap from fabrication; remelt or direct fabrication stock.",
        ["remelting", "fabrication stock"],
        ["steel manufacturing", "fabrication"],
    ),
    MaterialType(
        "metals.brass",
        "Brass scrap",
        "metals",
        ["brass", "brass turnings", "brass scrap"],
        "Brass scrap and turnings from machining; remelt for brass billet.",
        ["remelting", "ingot casting"],
        ["fittings manufacturing", "fabrication"],
    ),
    MaterialType(
        "plastics.pet_clear",
        "Clear PET flakes",
        "plastics",
        ["pet flakes", "pet bottles", "clear pet", "pet scrap", "pet"],
        "Washed clear PET flakes or bottles suitable for fibre and sheet extrusion.",
        ["fibre production", "sheet extrusion", "bottle-to-bottle recycling"],
        ["packaging", "textiles"],
    ),
    MaterialType(
        "plastics.polyethylene",
        "Polyethylene scrap",
        "plastics",
        ["hdpe", "ldpe", "polyethylene", "pe drums", "plastic drums"],
        "HDPE/LDPE scrap including drums, crates, and film; regranulate for pipe and moulding.",
        ["pipe extrusion", "injection moulding"],
        ["packaging", "piping"],
    ),
    MaterialType(
        "paper_cardboard.occ",
        "Corrugated cardboard (OCC)",
        "paper_cardboard",
        ["occ", "cardboard", "corrugated", "corrugated cardboard", "carton"],
        "Old corrugated containers and cardboard sheet waste; pulped into new linerboard.",
        ["packaging board", "new corrugated liners"],
        ["packaging"],
    ),
    MaterialType(
        "paper_cardboard.mixed_paper",
        "Mixed paper",
        "paper_cardboard",
        ["mixed paper", "newspaper", "office paper", "paper scrap"],
        "Mixed grade paper; de-inked and pulped for tissue or board.",
        ["tissue stock", "board making"],
        ["paper manufacturing"],
    ),
    MaterialType(
        "wood.pallet_timber",
        "Pallet timber",
        "wood",
        ["pallet", "pallet timber", "wood offcuts", "timber offcuts", "wooden pallets"],
        "Damaged pallets and timber offcuts; salvage boards or process into panels and biomass.",
        ["particle board", "animal bedding", "biomass"],
        ["furniture", "panel manufacturing"],
    ),
    MaterialType(
        "glass.cullet",
        "Glass cullet",
        "glass",
        ["glass", "cullet", "flint glass", "glass scrap"],
        "Clean container glass cullet; melts at lower energy than virgin batch.",
        ["new containers", "fibreglass"],
        ["glass manufacturing", "packaging"],
    ),
    MaterialType(
        "textiles.cotton",
        "Cotton textile waste",
        "textiles",
        ["cotton", "textile waste", "fabric offcuts", "cotton rags"],
        "Cotton-rich textile offcuts; wiping rags or mechanical fibre recycling.",
        ["wiping rags", "yarn spinning"],
        ["textiles"],
    ),
    MaterialType(
        "organics.food_waste",
        "Food and organic waste",
        "organics",
        ["food waste", "kitchen waste", "organic waste", "fruit waste"],
        "Source-separated organics; composted or digested to biogas.",
        ["composting", "biogas"],
        ["agriculture", "energy"],
    ),
    MaterialType(
        "electronics.pcb",
        "Printed circuit boards",
        "electronics",
        ["pcb", "circuit board", "e-waste", "printed circuit"],
        "Populated and unpopulated PCBs; precious and base metal recovery.",
        ["precious metal recovery", "copper recovery"],
        ["recycling", "electronics"],
    ),
    MaterialType(
        "chemicals.waste_oil",
        "Waste oil",
        "chemicals",
        ["waste oil", "used oil", "hydraulic oil", "solvent waste"],
        "Used mineral oils and solvent waste; re-refined or used in controlled energy recovery.",
        ["re-refining", "fuel blending"],
        ["chemical", "energy"],
    ),
]

_BY_ID = {entry.type_id: entry for entry in MATERIAL_TYPES}


def normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    cleaned = " ".join(label.strip().lower().split())
    return cleaned or None


def resolve_by_alias(text: str | None) -> tuple[MaterialType, str] | None:
    """Longest-alias substring match over the taxonomy. Deterministic."""
    normalized = normalize_label(text)
    if not normalized:
        return None
    best: tuple[MaterialType, str] | None = None
    for entry in MATERIAL_TYPES:
        for alias in entry.aliases:
            if alias in normalized:
                if best is None or len(alias) > len(best[1]):
                    best = (entry, alias)
    return best


def all_types() -> list[MaterialType]:
    return list(MATERIAL_TYPES)


def get_type(type_id: str) -> MaterialType | None:
    return _BY_ID.get(type_id)
