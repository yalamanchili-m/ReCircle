"""The six ERP entity schemas (blueprint Phase 16).

Each schema describes required/optional CSV columns (with header aliases),
typed validation, and the platform record it maps to. These schemas are the
contract shared by the implemented CSV adapter and future vendor API
adapters. Missing values are never silently defaulted; unknown/invalid
values are rejected row-by-row with reasons.

Import semantics are staging-only: rows land in ``erp_records`` keyed by
external ids; exports read live platform tables through separate, audited
``export`` mappings.
"""

from app.core.constants import (
    MATERIAL_CATEGORIES,
    ORGANIZATION_TYPES,
    RECOVERY_ROUTES,
    UNITS,
)

ORG_IMPORT_TYPES = tuple(
    t for t in ORGANIZATION_TYPES if t != "admin"
)

_FIELD_TYPES = {
    "string",
    "integer",
    "number",
    "date",
    "boolean",
}


class Field:
    """One CSV column spec (aliases accepted during header mapping)."""

    __slots__ = ("name", "aliases", "type", "enum", "required", "max_len", "minimum", "maximum", "date_pattern")

    def __init__(
        self,
        name: str,
        *,
        aliases: tuple[str, ...] = (),
        type: str = "string",
        enum: tuple[str, ...] = (),
        required: bool = False,
        max_len: int = 255,
        minimum: float | int | None = None,
        maximum: float | int | None = None,
    ):
        assert type in _FIELD_TYPES, type
        self.name = name
        self.aliases = (name,) + aliases
        self.type = type
        self.enum = enum
        self.required = required
        self.max_len = max_len
        self.minimum = minimum
        self.maximum = maximum


FIELD_EXTERNAL_ID = Field(
    "external_id",
    aliases=("external_id", "erp_id", "id"),
    type="string",
    required=True,
    max_len=100,
)


def _entities() -> dict[str, dict]:
    return {
        "organizations": {
            "name": "Organizations",
            "maps_to": "organizations (staging import; export reads live orgs)",
            "fields": (
                FIELD_EXTERNAL_ID,
                Field("name", type="string", required=True, max_len=160),
                Field("org_type", aliases=("organization_type", "type"), type="string", enum=ORG_IMPORT_TYPES, required=True),
                Field("region", aliases=("state",), type="string", max_len=100),
                Field("country", type="string", max_len=100),
                Field("industry", type="string", max_len=120),
            ),
        },
        "materials": {
            "name": "Materials (material master rows)",
            "maps_to": "waste_listings master data (staging import; export reads live listings)",
            "fields": (
                FIELD_EXTERNAL_ID,
                Field("title", aliases=("material_name", "label"), type="string", required=True, max_len=180),
                Field("category", aliases=("material_category",), type="string", enum=MATERIAL_CATEGORIES, required=True),
                Field("typical_unit", aliases=("unit",), type="string", enum=UNITS),
                Field("grade", type="string", max_len=100),
                Field("notes", aliases=("description",), type="string", max_len=1000),
            ),
        },
        "quantities": {
            "name": "Quantities (per-material stock/flow quantities)",
            "maps_to": "listing/requirement quantities (staging import; export reads live listing quantities)",
            "fields": (
                FIELD_EXTERNAL_ID,
                Field("material_external_id", aliases=("material_erp_id",), type="string", required=True, max_len=100),
                Field("quantity", type="number", required=True, minimum=0.000001),
                Field("unit", aliases=("quantity_unit",), type="string", enum=UNITS, required=True),
                Field("period_year", aliases=("year",), type="integer", minimum=1900, maximum=2100),
            ),
        },
        "locations": {
            "name": "Locations (site/region master rows)",
            "maps_to": "listing/org region data (staging import; export reads live regions)",
            "fields": (
                FIELD_EXTERNAL_ID,
                Field("city", type="string", required=True, max_len=100),
                Field("region", aliases=("state",), type="string", max_len=100),
                Field("country", type="string", max_len=100),
            ),
        },
        "transactions": {
            "name": "Transactions",
            "maps_to": "transactions (staging import; export reads the live trade chain)",
            "fields": (
                FIELD_EXTERNAL_ID,
                Field("buyer_external_id", aliases=("buyer_erp_id",), type="string", required=True, max_len=100),
                Field("seller_external_id", aliases=("seller_erp_id",), type="string", required=True, max_len=100),
                Field("material_external_id", aliases=("material_erp_id",), type="string", required=True, max_len=100),
                Field("quantity", type="number", required=True, minimum=0.000001),
                Field("unit", type="string", enum=UNITS, required=True),
                Field("value", aliases=("price",), type="number", minimum=0),
                Field("currency", type="string", max_len=3),
                Field("occurred_on", aliases=("transaction_date",), type="date", required=True),
                Field("status_external", aliases=("erp_status",), type="string", max_len=60),
            ),
            "references": {
                "buyer_external_id": "organizations",
                "seller_external_id": "organizations",
                "material_external_id": "materials",
            },
        },
        "recovery_records": {
            "name": "Recovery records",
            "maps_to": "recovery_records (staging import; export reads live recovery records)",
            "fields": (
                FIELD_EXTERNAL_ID,
                Field("transaction_external_id", aliases=("transaction_erp_id",), type="string", required=True, max_len=100),
                Field("recovered_quantity", type="number", required=True, minimum=0.000001),
                Field("unit", type="string", enum=UNITS, required=True),
                Field("route", aliases=("recovery_route",), type="string", enum=RECOVERY_ROUTES, required=True),
                Field("verified", type="boolean"),
                Field("verified_on", aliases=("verified_date",), type="date"),
            ),
            "references": {
                "transaction_external_id": "transactions",
            },
        },
    }


ENTITY_SCHEMAS: dict[str, dict] = _entities()
ENTITY_TYPES: tuple[str, ...] = tuple(ENTITY_SCHEMAS)
ERP_BOUNDARY_VERSION = "erp-boundary-v1"


def _posix_date(raw: str) -> bool:
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return False
    return all(part.isdigit() for part in raw.split("-"))


def validate_rows(entity_type: str, rows: list[dict], fieldnames: list[str]) -> dict:
    """Validate CSV rows against an entity schema.

    Returns accepted row_data dicts + explicit per-row rejection reasons.
    Missing required values are rejected, never zero-filled; enum ranges and
    numeric/date bounds are enforced deterministically.
    """
    schema = ENTITY_SCHEMAS[entity_type]
    fields = schema["fields"]
    alias_map: dict[str, Field] = {}
    for field in fields:
        for alias in field.aliases:
            alias_map[alias.strip().lower()] = field
    known = set(alias_map)
    unknown = [
        (raw or "").strip().lower()
        for raw in fieldnames
        if (raw or "").strip().lower() not in known
    ]
    missing_required = [
        field.name
        for field in fields
        if field.required and not any(a in [r.strip().lower() for r in fieldnames] for a in field.aliases)
    ]
    if missing_required:
        raise ValueError(
            f"missing required column(s) for entity '{entity_type}': "
            f"{', '.join(missing_required)}"
        )

    accepted: list[dict] = []
    rejected: list[dict] = []
    for index, raw_row in enumerate(rows):
        row_index = index + 2

        def cell_for(field: Field) -> str | None:
            value = None
            for alias in field.aliases:
                raw = raw_row.get(alias)
                if raw is not None:
                    value = raw.strip()
                    if value:
                        break
            return value if value else None

        parsed: dict = {}
        reason = None

        def field_error(name: str, detail: str) -> str:
            return f"row {row_index}: field '{name}' invalid ({detail})"

        for field in fields:
            raw = cell_for(field)
            if raw is None:
                if field.required:
                    reason = field_error(
                        field.name, "missing or blank — required, never defaulted"
                    )
                    break
                parsed[field.name] = None
                continue
            if field.type == "string":
                if field.enum:
                    normalized = raw.strip().lower().replace(" ", "_")
                    if normalized not in field.enum:
                        reason = field_error(
                            field.name, f"'{raw}' not one of {list(field.enum)}"
                        )
                        break
                else:
                    if len(raw) > field.max_len:
                        reason = field_error(field.name, f"longer than {field.max_len} characters")
                        break
                    normalized = raw
            elif field.type == "boolean":
                lower = raw.strip().lower()
                if lower in ("true", "yes", "1"):
                    normalized = True
                elif lower in ("false", "no", "0"):
                    normalized = False
                else:
                    reason = field_error(field.name, f"'{raw}' not a boolean (true/false)")
                    break
            elif field.type == "integer":
                try:
                    value_int = int(raw)
                except ValueError:
                    reason = field_error(field.name, f"'{raw}' not an integer")
                    break
                if field.minimum is not None and value_int < field.minimum:
                    reason = field_error(field.name, f"{value_int} < minimum {field.minimum}")
                    break
                if field.maximum is not None and value_int > field.maximum:
                    reason = field_error(field.name, f"{value_int} > maximum {field.maximum}")
                    break
                normalized = value_int
            elif field.type == "number":
                try:
                    value_num = float(raw.replace(",", ""))
                except ValueError:
                    reason = field_error(field.name, f"'{raw}' not a number")
                    break
                if field.minimum is not None and value_num < field.minimum:
                    reason = field_error(field.name, f"{value_num} < minimum {field.minimum}")
                    break
                if field.maximum is not None and value_num > field.maximum:
                    reason = field_error(field.name, f"{value_num} > maximum {field.maximum}")
                    break
                normalized = value_num
            elif field.type == "date":
                if not _posix_date(raw):
                    reason = field_error(field.name, f"'{raw}' not an ISO YYYY-MM-DD date")
                    break
                normalized = raw
            else:  # pragma: no cover
                reason = field_error(field.name, "unsupported type")
                break
            parsed[field.name] = normalized

        if reason is None:
            accepted.append(parsed)
        else:
            rejected.append({"row_index": row_index, "reason": reason})

    return {
        "accepted": accepted,
        "rejected": rejected,
        "unknown_columns": sorted(set(unknown)),
    }


def entities_payload() -> list[dict]:
    """Dictionary payload describing every entity schema (API/docs)."""
    entities = []
    for key, schema in ENTITY_SCHEMAS.items():
        entities.append(
            {
                "entity_type": key,
                "name": schema["name"],
                "maps_to": schema["maps_to"],
                "fields": [
                    {
                        "name": field.name,
                        "type": field.type if field.type != "enum" else "string",
                        "required": field.required,
                        "enum_values": list(field.enum) or None,
                        "aliases": list(field.aliases),
                    }
                    for field in schema["fields"]
                ],
                "references": schema.get("references"),
            }
        )
    return entities
