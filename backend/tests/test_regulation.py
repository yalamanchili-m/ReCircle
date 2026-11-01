"""Regulation-News Aggregator tests (blueprint Phase 13).

All feeds fetched in tests are version-controlled SYNTHETIC fixtures â€” either
injected via httpx.MockTransport (service level) or by monkeypatching the
fetch layer for API tests. No external network is ever touched. Fixture item
titles are explicitly marked SYNTHETIC so they can never be mistaken for real
regulation/news data in any database they land in.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AuditLog,
    RegulationNewsItem,
    RegulationNewsSource,
    RegulationRefreshRun,
    User,
)
from app.services import regulation
from app.services.regulation import ingest
from app.services.regulation.sources import SOURCE_REGISTRY, SOURCE_REGISTRY_VERSION

client = TestClient(app)

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>SYNTHETIC Test Regulator Feed</title>
  <item>
    <title>SYNTHETIC Rule: new reporting duties announced</title>
    <link>https://synthetic.test/rules/2026/annex-a?utm_source=feedlistener</link>
    <pubDate>Tue, 20 Oct 2026 09:30:00 GMT</pubDate>
    <description><p>SYNTHETIC fixture text about <b>plastic</b>
      plastic epr extended producer reporting duties. Placeholder only.</p></description>
  </item>
  <item>
    <title>SYNTHETIC Rule: hazardous waste transport notification</title>
    <link>https://synthetic.test/rules/2026/transport</link>
    <pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>
    <description>SYNTHETIC fixture text referring to hazardous waste transport.</description>
  </item>
</channel></rss>
"""

RSS_FEED_UPDATED = RSS_FEED.replace(
    "fixture text about <b>plastic</b>", "fixture text REVISED about plastic"
)

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>SYNTHETIC Test Register Feed</title>
  <entry>
    <title>SYNTHETIC EU decision on circular economy targets</title>
    <link rel="self" href="https://synthetic.test/docs/self-a"/>
    <link rel="alternate" href="https://synthetic.test/docs/a?q=keep&amp;utm_campaign=x"/>
    <published>2026-10-18T12:00:00Z</published>
    <summary>SYNTHETIC fixture summary about circular economy recycling targets.</summary>
  </entry>
</feed>
"""

FEED_FIXTURE_KEYS = (
    "epa_newsroom",
    "federal_register_epa_waste",
    "pib_environment_india",
    "eurlex_waste_legislation",
    "cpcb_updates",
    "broken_feed",
    "traffic_feed",
)

DEFAULT_FETCH_MAP = {
    "epa.gov": RSS_FEED,
    "federalregister.gov": RSS_FEED,
    "pib.gov.in": ATOM_FEED,
    "eur-lex": ATOM_FEED,
}


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    seed()
    _clean_fixture_rows()


def _clean_fixture_rows() -> None:
    """Remove any rows left by a previous module run of these tests."""
    with SessionLocal() as db:
        for key in FEED_FIXTURE_KEYS:
            source = db.scalar(select(RegulationNewsSource).where(RegulationNewsSource.key == key))
            if source is None:
                continue
            db.execute(delete(RegulationNewsItem).where(RegulationNewsItem.source_id == source.id))
            db.delete(source)
        db.commit()


def _install_fetch(monkeypatch, mapping: dict) -> None:
    """Replace the HTTP fetch layer with a fixture-backed dispatcher."""

    def fake_fetch(feed_url, transport=None, timeout=None):
        for needle, value in mapping.items():
            if needle in feed_url:
                if isinstance(value, Exception):
                    raise value
                return httpx.Response(200, content=value.encode("utf-8"))
        raise httpx.ConnectError("connection refused (fixture)")

    monkeypatch.setattr(ingest, "_fetch_http", fake_fetch)


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _refresh(token: str, monkeypatch, source_key: str | None = None) -> dict:
    _install_fetch(monkeypatch, DEFAULT_FETCH_MAP)
    query = f"?source_key={source_key}" if source_key else ""
    response = client.post(f"/api/regulation/refresh{query}", headers=_auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def _get_admin(db):
    return db.scalar(select(User).where(User.email == "admin@recircle.local"))


# ------------------------------------------------------------------- registry


def test_registry_curates_only_supported_sources_with_terms():
    assert SOURCE_REGISTRY_VERSION == "regulation-source-registry-v1"
    for entry in SOURCE_REGISTRY:
        assert regulation.sources._KEY_PATTERN.fullmatch(entry["key"])
        assert entry["jurisdiction"] in ("IN", "US", "EU", "GLOBAL")
        assert len(entry["terms_note"]) > 30, "usable terms note is mandatory"


def test_ensure_sources_idempotent_and_disabled_sources_flagged():
    with SessionLocal() as db:
        regulation.ensure_sources(db)  # may (re)create rows left by cleanup
        first_ids = db.scalars(select(RegulationNewsSource.id)).all()
        regulation.ensure_sources(db)
        second_ids = db.scalars(select(RegulationNewsSource.id)).all()
        db.commit()
    assert first_ids == second_ids, "rerun must never duplicate sources"
    no_feed = db.scalar(
        select(RegulationNewsSource).where(RegulationNewsSource.key == "cpcb_updates")
    )
    assert no_feed is not None
    assert no_feed.feed_url is None and no_feed.enabled is False


def test_sources_payload_lists_registry_and_flags_setup_needs():
    admin = _login("admin@recircle.local")
    body = client.get("/api/regulation/sources", headers=_auth(admin)).json()
    keys = {source["key"] for source in body["sources"]}
    assert set(FEED_FIXTURE_KEYS) - {"broken_feed", "traffic_feed"} <= keys
    cpcb = next(s for s in body["sources"] if s["key"] == "cpcb_updates")
    assert cpcb["needs_setup"] is True and cpcb["enabled"] is False
    assert cpcb["terms_note"]
    assert body["registry_version"] == SOURCE_REGISTRY_VERSION
    assert body["supported_jurisdictions"] == ["IN", "US", "EU", "GLOBAL"]
    assert "waste-management" in body["supported_topics"]


# --------------------------------------------------------------------- parser


def test_parse_feed_handles_rss_and_atom_and_cleans_text():
    entries_rss = ingest.parse_feed(RSS_FEED)
    assert len(entries_rss) == 2
    first = entries_rss[0]
    assert first["title"] == "SYNTHETIC Rule: new reporting duties announced"
    assert "utm_source" not in ingest.normalize_url(first["url"])[0]
    assert "SYNTHETIC fixture text about plastic" in first["description"]
    assert "placeholder" in (first["description"] or "").lower()
    assert first["published_at"] is not None
    assert first["published_at"].tzinfo is not None

    entries_atom = ingest.parse_feed(ATOM_FEED)
    assert len(entries_atom) == 1
    atom_entry = entries_atom[0]
    assert atom_entry["url"].startswith("https://synthetic.test/docs/a")
    assert "utm_campaign" not in ingest.normalize_url(atom_entry["url"])[0]
    assert "circular economy" in atom_entry["description"]


def test_parse_feed_rejects_malformed_xml():
    with pytest.raises(ValueError):
        ingest.parse_feed(b"<not-parseable")


def test_normalize_url_and_content_hash_are_stable():
    url, url_hash = ingest.normalize_url(
        "https://Example.COM:443/rules/a?utm_source=x&utm_medium=y&id=9"
    )
    assert url == "https://example.com/rules/a?id=9"
    assert url_hash == ingest.normalize_url(url)[1]

    other = ingest.normalize_url("https://example.com/rules/b")[1]
    assert other != url_hash
    assert ingest._content_hash("t", "d") == ingest._content_hash("t", "d")
    assert ingest._content_hash("t", "d") != ingest._content_hash("t", "d2")


# ------------------------------------------------------------------ ingestion


def test_refresh_ingests_deduplicates_and_updates_changed_content(monkeypatch):
    admin = _login("admin@recircle.local")
    source_key = "epa_newsroom"
    _clean_fixture_rows()  # deterministic start for exact counts

    first = _refresh(admin, monkeypatch, source_key)
    assert first["status"] == "success"
    assert first["stats"]["ingestion_version"] == ingest.INGESTION_VERSION
    assert first["totals"]["inserted"] == 2

    rerun = _refresh(admin, monkeypatch, source_key)
    assert rerun["totals"]["inserted"] == 0
    assert rerun["totals"]["unchanged"] == 2
    assert rerun["totals"]["updated"] == 0

    monkeypatch.setattr(
        ingest, "_fetch_http", lambda *a, **kw: httpx.Response(
            200, content=RSS_FEED_UPDATED.encode("utf-8")
        )
    )
    changed = client.post(
        f"/api/regulation/refresh?source_key={source_key}", headers=_auth(admin)
    ).json()
    assert changed["totals"]["updated"] == 1
    assert changed["totals"]["inserted"] == 0

    # dedupe kept the same rows (URL hash) - no duplicates appeared
    with SessionLocal() as db:
        source = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == source_key)
        )
        rows = db.scalars(
            select(RegulationNewsItem).where(RegulationNewsItem.source_id == source.id)
        ).all()
    assert len(rows) == 2
    revised = next(row for row in rows if "REVISED" in (row.description or ""))
    assert revised.title == "SYNTHETIC Rule: new reporting duties announced"
    _clean_fixture_rows()


def test_refresh_records_run_and_stats_and_is_audited(monkeypatch):
    admin = _login("admin@recircle.local")
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(RegulationRefreshRun))
        audits_before = db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "regulation.refresh")
        )
    _refresh(admin, monkeypatch, "epa_newsroom")
    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(RegulationRefreshRun))
        audits_after = db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "regulation.refresh")
        )
        latest = db.scalars(
            select(RegulationRefreshRun).order_by(RegulationRefreshRun.started_at.desc())
        ).first()
    assert after == before + 1
    assert audits_after == audits_before + 1
    assert latest.stats["ingestion_version"] == ingest.INGESTION_VERSION
    assert latest.stats["sources"][0]["source"] == "epa_newsroom"
    assert latest.triggered_by is not None
    assert latest.mode == "manual"


def test_item_type_jurisdiction_topics_derived_from_source(monkeypatch):
    admin = _login("admin@recircle.local")
    _refresh(admin, monkeypatch, "epa_newsroom")
    with SessionLocal() as db:
        source = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == "epa_newsroom")
        )
        rows = db.scalars(
            select(RegulationNewsItem).where(RegulationNewsItem.source_id == source.id)
        ).all()
    assert all(row.item_type == "news" for row in rows), "kind news -> news"
    assert all(row.jurisdiction == "US" for row in rows)
    assert all(row.issuer == source.name for row in rows)
    reporting = next(
        row for row in rows if row.title.endswith("reporting duties announced")
    )
    assert "plastics" in reporting.topics
    assert "reporting" in reporting.topics
    # published_at parsed from RFC 822 and persisted with a timezone
    assert reporting.published_at is not None
    assert reporting.published_at.tzinfo is not None


# provider failure handling


def test_unavailable_provider_degrades_gracefully_service_level():
    """A real (offline) fetch attempt through MockTransport fails safely."""
    admin = _login("admin@recircle.local")
    _clean_fixture_rows()
    with SessionLocal() as db:
        account = _get_admin(db)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused (fixture)")

        payload = ingest.refresh(
            db, account, "epa_newsroom", transport=httpx.MockTransport(handler)
        )
        db.commit()
    assert payload["status"] == "failed"
    failed_stats = payload["stats"]["sources"][0]
    assert "ConnectError" in failed_stats["failed"]
    assert "connection refused" in failed_stats["failed"]
    with SessionLocal() as db:
        run = db.scalars(
            select(RegulationRefreshRun).order_by(RegulationRefreshRun.started_at.desc())
        ).first()
        source = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == "epa_newsroom")
        )
        count = db.scalar(
            select(func.count())
            .select_from(RegulationNewsItem)
            .where(RegulationNewsItem.source_id == source.id)
        )
    assert run.status == "failed" and run.error
    assert count == 0  # outage could not corrupt or create partial junk rows


def test_rate_limited_and_malformed_sources_reported_safely():
    """Rate limits and malformed payloads become per-source failure statuses."""
    admin = _login("admin@recircle.local")
    with SessionLocal() as db:
        db.add(
            RegulationNewsSource(
                key="broken_feed",
                name="Broken (fixture source)",
                kind="news",
                jurisdiction="GLOBAL",
                homepage_url="https://broken.test",
                feed_url="https://broken.test/feed.xml",
                topics=["waste-management"],
                terms_note="fixture-only synthetic source; terms documented",
                enabled=True,
            )
        )
        db.add(
            RegulationNewsSource(
                key="traffic_feed",
                name="Rate limited (fixture source)",
                kind="news",
                jurisdiction="GLOBAL",
                homepage_url="https://traffic.test",
                feed_url="https://traffic.test/feed.xml",
                topics=["waste-management"],
                terms_note="fixture-only synthetic source; terms documented",
                enabled=True,
            )
        )
        db.commit()
    try:
        for broken_feed, expected_fragment in (
            ("traffic_feed", "429"),
            ("broken_feed", "malformed feed xml"),
        ):
            with SessionLocal() as db:
                account = _get_admin(db)

                def handler(request: httpx.Request, _b=broken_feed) -> httpx.Response:
                    if "broken" in str(request.url):
                        return httpx.Response(200, content=b"<not-parseable")
                    return httpx.Response(429)

                payload = ingest.refresh(
                    db, account, broken_feed, transport=httpx.MockTransport(handler)
                )
                db.commit()
            assert payload["status"] == "failed", payload
            failed = payload["stats"]["sources"][0]["failed"]
            assert expected_fragment in failed.lower()
            assert "authorization" not in failed.lower()  # never leak secrets
    finally:
        _clean_fixture_rows()


def test_staleness_signal():
    admin = _login("admin@recircle.local")
    payload = client.get("/api/regulation/sources", headers=_auth(admin)).json()
    epa = next(s for s in payload["sources"] if s["key"] == "epa_newsroom")
    assert epa["stale"] is False
    with SessionLocal() as db:
        source = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == "epa_newsroom")
        )
        source.last_item_at = datetime.now(timezone.utc) - timedelta(
            days=ingest.STALE_SOURCE_DAYS + 5
        )
        db.commit()
    payload = client.get("/api/regulation/sources", headers=_auth(admin)).json()
    epa = next(s for s in payload["sources"] if s["key"] == "epa_newsroom")
    assert epa["stale"] is True
    with SessionLocal() as db:
        source = db.scalar(
            select(RegulationNewsSource).where(RegulationNewsSource.key == "epa_newsroom")
        )
        source.last_item_at = None
        db.commit()


# ----------------------------------------------------------------------- API


def test_items_requires_auth_and_filters_work(monkeypatch):
    # Some rows may already exist from earlier module tests in this file
    assert client.get("/api/regulation/items").status_code == 401
    buyer = _login("buyer@recircle.local")
    admin = _login("admin@recircle.local")
    _refresh(admin, monkeypatch, "epa_newsroom")
    body = client.get("/api/regulation/items", headers=_auth(buyer)).json()
    assert body["total"] >= 2
    news_only = client.get(
        "/api/regulation/items?item_type=news", headers=_auth(buyer)
    ).json()
    assert news_only["total"] >= 1
    assert all(item["item_type"] == "news" for item in news_only["items"])
    us_only = client.get(
        "/api/regulation/items?jurisdiction=US", headers=_auth(buyer)
    ).json()
    assert us_only["total"] >= 1
    assert all(item["jurisdiction"] == "US" for item in us_only["items"])
    topic_items = client.get(
        "/api/regulation/items?topic=plastics", headers=_auth(buyer)
    ).json()
    assert topic_items["total"] >= 1
    assert all("plastics" in item["topics"] for item in topic_items["items"])
    searched = client.get(
        "/api/regulation/items?q=hazardous", headers=_auth(buyer)
    ).json()
    assert searched["total"] >= 1
    # pagination is stable and bounded
    page = client.get(
        "/api/regulation/items?limit=1&offset=1", headers=_auth(buyer)
    ).json()
    assert page["total"] == body["total"] and len(page["items"]) == 1
    bad_type = client.get("/api/regulation/items?item_type=nope", headers=_auth(buyer))
    assert bad_type.status_code == 422


def test_item_detail_labels_summaries_and_disclaims_legal_advice(monkeypatch):
    buyer = _login("buyer@recircle.local")
    admin = _login("admin@recircle.local")
    _refresh(admin, monkeypatch, "epa_newsroom")
    listing = client.get("/api/regulation/items?limit=1", headers=_auth(buyer)).json()
    item = listing["items"][0]
    detail = client.get(
        f"/api/regulation/items/{item['id']}", headers=_auth(buyer)
    ).json()
    assert detail["title"] == item["title"] == "SYNTHETIC Rule: new reporting duties announced"
    assert detail["summary_kind"] == "source_excerpt"
    assert detail["summary_label"] == "Source excerpt (automated)"
    assert detail["description"] is not None
    assert any("not legal advice" in d for d in detail["disclaimers"])
    # link back to the original source is always present
    assert detail["url"].startswith("https://synthetic.test/")
    missing = client.get(f"/api/regulation/items/{uuid.uuid4()}", headers=_auth(buyer))
    assert missing.status_code == 404


def test_refresh_is_admin_only_and_unknown_key_422():
    buyer = _login("buyer@recircle.local")
    assert (
        client.post("/api/regulation/refresh", headers=_auth(buyer)).status_code == 403
    )
    assert client.post("/api/regulation/refresh").status_code == 401
    admin = _login("admin@recircle.local")
    bad = client.post(
        "/api/regulation/refresh?source_key=nonexistent_source", headers=_auth(admin)
    )
    assert bad.status_code == 422
    disabled = client.post(
        "/api/regulation/refresh?source_key=cpcb_updates", headers=_auth(admin)
    )
    assert disabled.status_code == 422
    with SessionLocal() as db:
        run = db.scalars(
            select(RegulationRefreshRun).order_by(RegulationRefreshRun.started_at.desc())
        ).first()
    assert run is not None and run.error
    # refresh run history endpoint is admin-gated
    assert client.get("/api/regulation/refresh-runs").status_code == 401
    assert (
        client.get("/api/regulation/refresh-runs", headers=_auth(buyer)).status_code
        == 403
    )
    runs = client.get("/api/regulation/refresh-runs", headers=_auth(admin))
    assert runs.status_code == 200
    assert len(runs.json()["runs"]) >= 1


def test_summarize_llm_is_opt_in_labeled_and_falls_back_safely():
    excerpt, kind = ingest.summarize(
        "First 400 characters of a long description" + ("x" * 500),
        llm_enabled=False,
    )
    assert kind == "source_excerpt"
    assert len(excerpt) == 400

    ai_summary, ai_kind = ingest.summarize(
        "source text",
        llm_enabled=True,
        call_llm=lambda text: "AI restatement of the source text.",
    )
    assert ai_kind == "ai_generated"
    assert ai_summary == "AI restatement of the source text."

    # Any model failure quietly degrades to the source excerpt
    fallback_summary, fallback_kind = ingest.summarize(
        "source text", llm_enabled=True, call_llm=_raise
    )
    assert fallback_kind == "source_excerpt"
    assert fallback_summary == "source text"


def _raise(_text: str) -> str:
    raise RuntimeError("model unavailable")
