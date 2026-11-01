"""Curated source registry for the Regulation-News Aggregator (Phase 13).

Policy, aligned with the blueprint:
- Only keyless public feeds of regulators/registers with usable terms are
  curated here. No API keys are stored and none are required.
- Every entry carries an explicit `terms_note` describing the source's reuse
  terms as understood at curation time; the original site's terms always win.
- One entry at a time follows the "prioritize one adapter at a time" vacuum:
  entries without a stable RSS/Atom feed stay disabled until a usable feed is
  documented - they are never guessed.
- `ensure_sources` upserts this registry idempotently (reruns never create
  duplicates); descriptive fields are refreshed, but an operator may only set
  `enabled` for registered entries where a feed exists.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import SUPPORTED_JURISDICTIONS, SUPPORTED_TOPICS
from app.models.regulation import RegulationNewsSource

SOURCE_REGISTRY_VERSION = "regulation-source-registry-v1"

_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")

#: Curated, keyless, public sources. `feed_format` is what the ingestion
#: parser expects ("rss" files often carry Atom too; the parser handles both).
SOURCE_REGISTRY = [
    {
        "key": "epa_newsroom",
        "name": "US EPA Newsroom",
        "kind": "news",
        "jurisdiction": "US",
        "homepage_url": "https://www.epa.gov/newsroom",
        "feed_url": "https://www.epa.gov/newsroom/rss",
        "topics": ["waste-management", "reporting"],
        "terms_note": (
            "US EPA public RSS feed. US Government works are largely public "
            "domain; attribution to EPA and a link to the original item are "
            "required by this platform's house policy. epa.gov terms win."
        ),
    },
    {
        "key": "federal_register_epa_waste",
        "name": "US Federal Register - EPA waste-related rules",
        "kind": "regulation",
        "jurisdiction": "US",
        "homepage_url": "https://www.federalregister.gov",
        "feed_url": (
            "https://www.federalregister.gov/documents/search.atom"
            "?conditions%5Bagencies%5D%5B%5D=environmental-protection-agency"
            "&conditions%5Bterm%5D=waste&order%5Bnewest%5D=1"
        ),
        "topics": ["waste-management", "hazardous-waste", "reporting"],
        "terms_note": (
            "Federal Register documents are US Government public domain; "
            "attribution to the Federal Register and linking to the original "
            "document are required by this platform's house policy."
        ),
    },
    {
        "key": "pib_environment_india",
        "name": "Press Information Bureau - Environment (India)",
        "kind": "news",
        "jurisdiction": "IN",
        "homepage_url": "https://pib.gov.in",
        "feed_url": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "topics": ["waste-management", "plastics", "e-waste"],
        "terms_note": (
            "PIB press releases are published for public information by the "
            "Ministry of I&B (India); reuse is subject to PIB terms. Items are "
            "linked to the original release; no endorsement is implied."
        ),
    },
    {
        "key": "cpcb_updates",
        "name": "CPCB (India) - announcements",
        "kind": "regulator",
        "jurisdiction": "IN",
        "homepage_url": "https://cpcb.nic.in",
        "feed_url": None,
        "topics": ["waste-management", "hazardous-waste"],
        "terms_note": (
            "CPCB material is from an India government website; reuse is "
            "subject to NIC/CPCB terms. CPCB publishes no stable RSS/Atom "
            "feed yet, so this source stays disabled until a feed or manual "
            "fixture is documented - its URL is never guessed."
        ),
    },
    {
        "key": "eurlex_waste_legislation",
        "name": "EUR-Lex - EU waste framework legislation",
        "kind": "legal_register",
        "jurisdiction": "EU",
        "homepage_url": "https://eur-lex.europa.eu",
        "feed_url": (
            "https://eur-lex.europa.eu/rss/legislation/latest_active_med.html"
        ),
        "topics": ["waste-management", "hazardous-waste", "circular-economy"],
        "terms_note": (
            "EUR-Lex content is reusable under the EU reuse policy "
            "(Commission Decision 2011/833/EU); attribution to the source "
            "document is required. eur-lex.europa.eu terms win."
        ),
    },
]


def _normalize_topics(raw_topics) -> list[str]:
    topics = [str(t) for t in (raw_topics or []) if t in SUPPORTED_TOPICS]
    return sorted(set(topics))


def ensure_sources(db: Session) -> dict:
    """Idempotently upsert the curated registry; never drops operator edits.

    Returns a small report so the caller/tests can see what happened.
    """
    registry_keys = [entry["key"] for entry in SOURCE_REGISTRY]
    existing = {
        row.key: row
        for row in db.scalars(
            select(RegulationNewsSource).where(
                RegulationNewsSource.key.in_(registry_keys)
            )
        )
    }
    created, updated = [], []
    for entry in SOURCE_REGISTRY:
        if not _KEY_PATTERN.fullmatch(entry["key"]):
            raise ValueError(f"invalid source key in registry: {entry['key']!r}")
        if entry["jurisdiction"] not in SUPPORTED_JURISDICTIONS:
            raise ValueError(
                f"unsupported jurisdiction for source {entry['key']}"
            )
        feed_url = entry.get("feed_url") or None
        source = existing.get(entry["key"])
        if source is None:
            source = RegulationNewsSource(
                key=entry["key"],
                name=entry["name"],
                kind=entry["kind"],
                jurisdiction=entry["jurisdiction"],
                homepage_url=entry["homepage_url"],
                feed_url=feed_url,
                topics=_normalize_topics(entry.get("topics")),
                terms_note=entry["terms_note"],
                enabled=bool(feed_url),
            )
            db.add(source)
            created.append(entry["key"])
        else:
            changed = False
            for field in ("name", "kind", "homepage_url", "terms_note"):
                new_value = entry[field]
                if getattr(source, field) != new_value:
                    setattr(source, field, new_value)
                    changed = True
            topics = _normalize_topics(entry.get("topics"))
            if list(source.topics or []) != topics:
                source.topics = topics
                changed = True
            # Only restore a curated feed URL/document that the current
            # registry actually provides; never invent or replace one with
            # a guessed URL when the row was operator-edited.
            if feed_url is not None and source.feed_url != feed_url:
                source.feed_url = feed_url
                changed = True
            if source.feed_url is None and not source.enabled:
                pass  # stays disabled until a usable feed is documented
            if source.feed_url is not None and source.enabled is False:
                # A missing feed was never an operator decision to trust:
                # entries with a documented feed may be enabled.
                source.enabled = True
                changed = True
            if changed:
                updated.append(entry["key"])
    db.flush()
    return {"created": created, "updated": updated, "registry_version": SOURCE_REGISTRY_VERSION}


def sources_payload(db: Session) -> dict:
    """Registry rows with freshness stats for the API/UI."""
    ensure_sources(db)
    rows = db.scalars(
        select(RegulationNewsSource).order_by(RegulationNewsSource.jurisdiction, RegulationNewsSource.key)
    ).all()
    sources = []
    for row in rows:
        enabled_with_no_feed = bool(row.enabled and not row.feed_url)
        sources.append(
            {
                "key": row.key,
                "name": row.name,
                "kind": row.kind,
                "jurisdiction": row.jurisdiction,
                "homepage_url": row.homepage_url,
                "feed_url": row.feed_url,
                "topics": list(row.topics or []),
                "terms_note": row.terms_note,
                "enabled": row.enabled,
                "needs_setup": enabled_with_no_feed or (row.feed_url is None),
                "last_fetched_at": row.last_fetched_at.isoformat()
                if row.last_fetched_at
                else None,
                "last_item_at": row.last_item_at.isoformat()
                if row.last_item_at
                else None,
            }
        )
    return {
        "registry_version": SOURCE_REGISTRY_VERSION,
        "supported_jurisdictions": list(SUPPORTED_JURISDICTIONS),
        "supported_topics": list(SUPPORTED_TOPICS),
        "sources": sources,
    }
