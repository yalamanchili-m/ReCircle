"""Optional Ollama-assisted description enrichment.

Safety rules (implementation plan, section 6.5):
- The model never invents grades, compositions, certifications, hazard
  classifications, or environmental factors; only explicitly supported values
  are suggested.
- All model output is validated against Pydantic schemas; invalid values are
  dropped rather than trusted.
- Every suggestion is advisory and requires user confirmation before being
  stored as authoritative data.
- Ollama unavailability, timeouts, and malformed output degrade gracefully to
  a deterministic rule-based fallback; the rest of the application never
  depends on the model.
- The matching score is never computed by the LLM.
"""

import json
import re

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.constants import MATERIAL_CATEGORIES, UNITS

UNIT_ALIASES = {
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "tonne": "tonne",
    "tonnes": "tonne",
    "ton": "tonne",
    "tons": "tonne",
    "litre": "litre",
    "litres": "litre",
    "liter": "litre",
    "liters": "litre",
    "unit": "unit",
    "units": "unit",
    "piece": "unit",
    "pieces": "unit",
}

CATEGORY_KEYWORDS = {
    "metals": ("steel", "aluminium", "aluminum", "copper", "brass", "iron", "zinc", "metal"),
    "plastics": ("plastic", "pet", "hdpe", "ldpe", "polyethylene", "polypropylene", "polymer", "pvc"),
    "paper_cardboard": ("cardboard", "paper", "occ", "carton", "corrugated"),
    "wood": ("wood", "timber", "pallet", "lumber", "sawdust"),
    "glass": ("glass",),
    "textiles": ("textile", "fabric", "cloth", "cotton"),
    "organics": ("organic", "compost", "food waste", "biomass"),
    "electronics": ("e-waste", "electronic", "pcb", "circuit board", "computer"),
    "chemicals": ("chemical", "solvent", "oil", "sludge"),
}

QUANTITY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|kgs|kilogram|kilograms|tonne|tonnes|ton|tons|litre|litres|liter|liters|units|unit|pieces|piece)\b",
    re.IGNORECASE,
)


class OllamaSuggestion(BaseModel):
    """Schema the model is asked to fill. Invalid values are dropped later."""

    category: str | None = None
    material_name: str | None = None
    composition: str | None = None
    grade: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    notes: str | None = None


class EnrichmentSuggestions(BaseModel):
    """Validated, cleaned suggestions returned to the user."""

    category: str | None = None
    material_name: str | None = None
    composition: str | None = None
    grade: str | None = None
    quantity: float | None = None
    unit: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    notes: str | None = None


class EnrichmentResponse(BaseModel):
    available: bool
    source: str  # "ollama" or "fallback"
    needs_review: bool = True
    suggestions: EnrichmentSuggestions


def _prompt(description: str) -> str:
    return (
        "You extract structured data from industrial waste material descriptions. "
        "Reply with ONLY a JSON object, no other text.\n"
        "Rules: never invent values; use null for anything not explicitly stated "
        "in the text; never invent a grade, composition, certification, or hazard "
        "classification.\n"
        f'Allowed categories: {", ".join(MATERIAL_CATEGORIES)}.\n'
        f'Allowed units: {", ".join(UNITS)}.\n\n'
        f'Description: "{description}"\n\n'
        'JSON object keys: category, material_name, composition, grade, quantity '
        "(number), unit, missing_information (list of strings), notes."
    )


def _call_ollama(description: str) -> dict:
    settings = get_settings()
    response = httpx.post(
        f"{settings.ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": settings.ollama_model,
            "prompt": _prompt(description),
            "stream": False,
            "format": "json",
        },
        timeout=settings.ollama_timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    return json.loads(body["response"])


def _fallback_extract(description: str) -> EnrichmentSuggestions:
    """Deterministic rule-based extraction used when the model is unavailable."""
    text = description.lower()

    category = None
    for candidate, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            category = candidate
            break

    quantity = None
    unit = None
    match = QUANTITY_PATTERN.search(text)
    if match:
        quantity = float(match.group(1))
        unit = UNIT_ALIASES.get(match.group(2).lower())

    material_name = None
    if category and quantity is not None:
        pass  # names are hard to extract reliably; leave to the user

    missing: list[str] = []
    if category is None:
        missing.append("material category")
    if quantity is None or unit is None:
        missing.append("quantity and unit")
    if "grade" not in text and "composition" not in text:
        missing.append("composition or grade (do not guess)")
    missing.append("location (city/region)")
    missing.append("asking price (optional)")

    return EnrichmentSuggestions(
        category=category,
        material_name=material_name,
        composition=None,
        grade=None,
        quantity=quantity,
        unit=unit,
        missing_information=missing,
        notes=(
            "Rule-based offline extraction. Values found directly in the text only; "
            "please review and complete the missing fields."
        ),
    )


def _validate_model_suggestion(raw: dict) -> EnrichmentSuggestions:
    parsed = OllamaSuggestion.model_validate(raw)

    category = parsed.category if parsed.category in MATERIAL_CATEGORIES else None
    unit = parsed.unit if parsed.unit in UNITS else None

    missing = list(parsed.missing_information)
    if category is None and "material category" not in missing:
        missing.append("material category")
    if (parsed.quantity is None or unit is None) and "quantity and unit" not in missing:
        missing.append("quantity and unit")

    return EnrichmentSuggestions(
        category=category,
        material_name=(parsed.material_name or "").strip() or None,
        composition=(parsed.composition or "").strip() or None,
        grade=(parsed.grade or "").strip() or None,
        quantity=parsed.quantity,
        unit=unit,
        missing_information=missing,
        notes=(parsed.notes or "").strip() or None,
    )


def enrich_description(description: str) -> EnrichmentResponse:
    """Try Ollama first; fall back to deterministic extraction on any failure."""
    try:
        raw = _call_ollama(description)
        suggestions = _validate_model_suggestion(raw)
        return EnrichmentResponse(
            available=True,
            source="ollama",
            suggestions=suggestions,
        )
    except (
        httpx.HTTPError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        TypeError,
    ):
        suggestions = _fallback_extract(description)
        return EnrichmentResponse(
            available=False,
            source="fallback",
            suggestions=suggestions,
        )