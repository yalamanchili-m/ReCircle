"""Feed ingestion, deduplication, and refresh-run recording (Phase 13).

Design rules taken from the blueprint:
- Fetch only keyless public feeds; provider/LLM summarization is optional and
  clearly labeled when used. LLM failures degrade to source-excerpt summaries.
- Deduplicate by normalized URL hash per source; detect content changes via a
  content hash over title + description.
- Every refresh attempt (including failures) is recorded in
  `regulation_refresh_runs` in the same transaction the route commits.
- Unavailable providers, timeouts, rate-limit responses, and malformed feeds
  degrade to a per-source failure status; PostgreSQL and inventory/marketplace
  workflows are never affected.
- Original titles/description text are preserved verbatim; generated
  summaries are labeled `source_excerpt` or `ai_generated` and must never be
  read as legal advice.
"""

import hashlib
import html
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User
from app.models.regulation import RegulationNewsItem, RegulationNewsSource, RegulationRefreshRun
from app.services.regulation.sources import ensure_sources

INGESTION_VERSION = "regulation-ingest-v1"

MAX_ITEMS_PER_SOURCE = 25
REQUEST_TIMEOUT_SECONDS = 15
RATE_LIMIT_DELAY_SECONDS = 1.0
STALE_SOURCE_DAYS = 90

DISCLAIMERS = (
    "Items are aggregated from third-party public sources; the linked original "
    "source is always authoritative.",
    "AI-generated summaries are clearly labeled, may be imperfect, and are "
    "informational only - they are not legal advice or compliance guidance.",
    "Source-excerpt summaries are automated extractions of the publisher's own "
    "text and carry the publisher's wording, not ReCircle's interpretation.",
)

SUMMARY_LABELS = {
    "source_excerpt": "Source excerpt (automated)",
    "ai_generated": "AI-generated summary",
}

_TAG_PATTERN = re.compile(r"<[^>]+>")
_FT_PATTERN = re.compile(
    r"(\b(?:plastic|e-?waste|electronic|hazardous|extended prod(?:ucer|ucers?) "
    r"|epr|recycl|reporting|notif(?:y|ication)|circular)\b)",
    re.IGNORECASE,
)
_TOPIC_KEYWORD_MAP = (
    ("plastics", ("plastic",)),
    ("e-waste", ("e-waste", "ewaste", "electronic waste")),
    ("hazardous-waste", ("hazardous",)),
    ("epr", ("epr", "extended producer", "extended prod")),
    ("recycling", ("recycl",)),
    ("reporting", ("reporting", "notification", "compliance")),
    ("circular-economy", ("circular",)),
    ("waste-management", ("waste", "landfill", "environment")),
)


def _clean_text(value: str | None, limit: int = 3000) -> str | None:
    """Strip markup/HTML entities and hostile whitespace from feed text."""
    if not value:
        return None
    text = html.unescape(_TAG_PATTERN.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:limit]


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = parsedate_to_datetime(raw)  # RFC 822 (RSS pubDate)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_url(url: str) -> tuple[str, str]:
    """Canonicalize a feed URL and return (clean_url, sha256 url_hash)."""
    parts = urlsplit(url.strip())
    netloc = parts.netloc.lower()
    default_ports = {"https": 443, "http": 80}
    if parts.port is not None and default_ports.get(parts.scheme.lower()) == parts.port:
        netloc = netloc.rsplit(":", 1)[0]
    query_pairs = [
        pair
        for pair in (parts.query.split("&") if parts.query else [])
        if not pair.lower().startswith("utm_")
    ]
    clean = urlunsplit((parts.scheme.lower(), netloc, parts.path, "&".join(query_pairs), ""))
    return clean, hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _content_hash(title: str, description: str | None) -> str:
    payload = f"{title}\n\n{description or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_feed(content: bytes | str) -> list[dict]:
    """Parse an RSS 2.0 or Atom feed into normalized entry dicts.

    Namespace-agnostic: entries are matched by local tag names, so both
    serializers work on mixed feeds. Malformed XML raises ValueError.
    """
    import xml.etree.ElementTree as ET

    def local(tag: str) -> str:
        return tag.rpartition("}")[2].lower()

    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError(f"malformed feed XML: {error}") from error

    entries: list[dict] = []
    for element in root.iter():
        name = local(element.tag)
        if name not in ("item", "entry"):
            continue
        entry: dict = {}
        link_href = None
        for child in element:
            child_name = local(child.tag)
            if child_name == "title":
                entry["title"] = _clean_text(child.text)
            elif child_name == "link":
                href = child.get("href") or (child.text or "").strip()
                if href and child.get("rel") != "self":
                    link_href = href
            elif child_name in ("pubdate", "dc:date", "published", "updated"):
                parsed = _parse_date(child.text)
                if parsed and not entry.get("published_at"):
                    entry["published_at"] = parsed
            elif child_name in ("description", "summary", "content"):
                if entry.get("description") is None:
                    entry["description"] = _clean_text(
                        "".join(child.itertext())
                    )
        entry["url"] = link_href
        if not entry.get("title") or not entry.get("url"):
            continue  # a source item without title/link is unusable
        entries.append(entry)
    return entries


def topics_for(source_topics, title: str, description: str | None) -> list[str]:
    """Merge curated source topics with rule-based topic tags from the text."""
    topics = set(source_topics or [])
    haystack = f"{title} {description or ''}".lower()
    for search in _FT_PATTERN.findall(haystack):
        for topic, keywords in _TOPIC_KEYWORD_MAP:
            if any(keyword in search or search in keyword for keyword in keywords):
                topics.add(topic)
        if search in ("epr",):
            topics.add("epr")
    return sorted(topics)


def summarize(
    description: str | None,
    *,
    llm_enabled: bool | None = None,
    call_llm=None,
) -> tuple[str | None, str]:
    """Label-safe summary: source excerpt, or opt-in AI-generated summary.

    An LLM summary is only produced when configured; any failure falls back to
    the source excerpt so ingestion never blocks on the model.
    """
    excerpt = (description or "")[:400].strip()
    if llm_enabled is None:
        llm_enabled = get_settings().regulation_llm_summaries_enabled
    if not llm_enabled:
        return (excerpt or None), "source_excerpt"
    try:
        caller = call_llm or _call_ollama
        raw = caller(excerpt)
    except Exception:  # noqa: BLE001 - model failures must never break ingest
        return (excerpt or None), "source_excerpt"
    summary = _clean_text(str(raw), limit=600)
    if not summary:
        return (excerpt or None), "source_excerpt"
    return summary, "ai_generated"


def _call_ollama(text: str) -> str:
    """Optional Ollama summarization pass (JSON-schema free, plain text)."""
    settings = get_settings()
    response = httpx.post(
        f"{settings.ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": settings.ollama_model,
            "prompt": (
                "You summarize regulatory and news items for an industrial "
                "circular-economy platform. Summarize the text in at most 3 "
                "sentences. Restate only what the text states; add no "
                "interpretation, advice, or facts of your own.\n\n"
                f'Text: "{text}"'
            ),
            "stream": False,
        },
        timeout=settings.ollama_timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    return (body.get("response") or "").strip()


def _fetch_http(feed_url: str, transport: httpx.BaseTransport | None,
                timeout: int) -> httpx.Response:
    client_options: dict = {"timeout": timeout, "follow_redirects": True}
    if transport is not None:
        client_options["transport"] = transport
    with httpx.Client(**client_options) as client:
        response = client.get(
            feed_url,
            headers={"User-Agent": "ReCircleRegulationAggregator/1.0 (+local)"},
        )
    if response.status_code == 429:
        raise RuntimeError("source responded 429 (rate limited); retry later")
    response.raise_for_status()
    return response


def ingest_source(
    db: Session,
    source: RegulationNewsSource,
    *,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> dict:
    """Fetch, parse, deduplicate, and persist one source. Never raises."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    stats: dict = {"source": source.key, "inserted": 0, "updated": 0, "unchanged": 0,
                   "failed": None}
    if not source.feed_url:
        stats["failed"] = "no usable feed documented for this source; kept disabled"
        return stats
    try:
        time.sleep(RATE_LIMIT_DELAY_SECONDS) if transport is None else None
        response = _fetch_http(source.feed_url, transport, settings.regulation_fetch_timeout_seconds)
        entries = parse_feed(response.content)
        if not entries:
            raise ValueError("feed contained no usable title/link entries")
        existing_rows = {
            row.url_hash: row
            for row in db.scalars(
                select(RegulationNewsItem).where(RegulationNewsItem.source_id == source.id)
            )
        }
        for entry in entries[: settings.regulation_max_items_per_source]:
            clean_url, url_hash = normalize_url(str(entry["url"]))
            description = entry.get("description")
            content_hash = _content_hash(str(entry["title"]), description)
            summary, summary_kind = summarize(
                description,
                llm_enabled=False if transport is not None else None,
            )
            item_type = "news" if source.kind == "news" else "regulation"
            row = existing_rows.get(url_hash)
            if row is None:
                row = RegulationNewsItem(
                    source_id=source.id,
                    item_type=item_type,
                    title=str(entry["title"]),
                    url=clean_url,
                    url_hash=url_hash,
                    content_hash=content_hash,
                    issuer=source.name,
                    jurisdiction=source.jurisdiction,
                    topics=topics_for(source.topics, str(entry["title"]), description),
                    description=description,
                    summary=summary,
                    summary_kind=summary_kind,
                    published_at=entry.get("published_at"),
                    fetched_at=now,
                )
                db.add(row)
                stats["inserted"] += 1
            elif row.content_hash != content_hash:
                row.title = str(entry["title"])
                row.description = description
                row.summary = summary
                row.summary_kind = summary_kind
                row.content_hash = content_hash
                row.topics = topics_for(source.topics, str(entry["title"]), description)
                row.published_at = entry.get("published_at") or row.published_at
                row.fetched_at = now
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        db.flush()
        source.last_fetched_at = now
        source.last_item_at = max(
            (
                row.published_at
                for row in db.scalars(
                    select(RegulationNewsItem).where(
                        RegulationNewsItem.source_id == source.id
                    )
                )
                if row.published_at is not None
            ),
            default=None,
        )
        source.updated_at = now
    except (httpx.HTTPError, ValueError, RuntimeError) as error:
        stats["failed"] = _safe_error(error)
    return stats


def _safe_error(error: Exception) -> str:
    """Collapse connectivity/parse errors into safe, secret-free messages."""
    name = type(error).__name__
    message = str(error)
    message = re.sub(r"(?i)(api[_-]?key|token|authorization)[=:;\s]+\S+", r"\1=REDACTED", message)
    return f"{name}: {message}"[:500]


def refresh(
    db: Session,
    current_user: User | None,
    source_key: str | None = None,
    *,
    mode: str = "manual",
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Refresh one or all curated sources; every attempt is recorded."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    ensure_sources(db)
    query = select(RegulationNewsSource).order_by(RegulationNewsSource.key)
    if source_key:
        query = query.where(RegulationNewsSource.key == source_key)
    sources = [row for row in db.scalars(query) if row.enabled and row.feed_url]
    if source_key and not sources:
        known = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == source_key)
        )
        error = (
            "unknown source key"
            if known is None
            else "source has no usable feed or is disabled"
        )
        run = RegulationRefreshRun(
            status="failed",
            error=error,
            mode=mode,
            params={"source_key": source_key},
            stats={"sources": []},
            triggered_by=current_user.id if current_user else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        raise ValueError(error)

    statuses = [ingest_source(db, source, transport=transport) for source in sources]
    succeeded = sum(1 for item in statuses if item["failed"] is None)
    failed = sum(1 for item in statuses if item["failed"] is not None)
    totals = {
        "inserted": sum(item["inserted"] for item in statuses),
        "updated": sum(item["updated"] for item in statuses),
        "unchanged": sum(item["unchanged"] for item in statuses),
    }
    if sources and succeeded == 0:
        status = "failed"
    else:
        status = "success"
    note = None
    if not sources:
        note = "no enabled sources with a usable feed; nothing to refresh"
    stats = {
        "ingestion_version": INGESTION_VERSION,
        "sources": statuses,
        "source_count": len(statuses),
        "succeeded": succeeded,
        "failed_sources": failed,
        "totals": totals,
        "summary_mode": "ai_generated_labeled"
        if get_settings().regulation_llm_summaries_enabled
        else "source_excerpt",
        "note": note,
    }
    run = RegulationRefreshRun(
        status=status,
        error=None if failed == 0 else f"{failed} of {len(statuses)} sources failed",
        mode=mode,
        params={"source_key": source_key},
        stats=stats,
        runtime_ms=int((time.monotonic() - started) * 1000),
        triggered_by=current_user.id if current_user else None,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    return {
        "status": status,
        "stats": stats,
        "totals": totals,
        "run_id": str(run.id),
        "runtime_ms": run.runtime_ms,
        "disclaimers": DISCLAIMERS,
    }


def is_stale(source: RegulationNewsSource, *, now: datetime | None = None) -> bool:
    """A source is stale when its newest item is older than STALE_SOURCE_DAYS."""
    now = now or datetime.now(timezone.utc)
    reference = now
    if source.last_item_at is not None:
        if source.last_item_at.tzinfo is None:
            reference = source.last_item_at.replace(tzinfo=timezone.utc)
        else:
            reference = source.last_item_at
    return reference < now - timedelta(days=STALE_SOURCE_DAYS)
