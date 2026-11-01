"use client";

import { useEffect, useState, FormEvent } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { getStoredUser } from "@/lib/auth";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type {
  RegulationItem,
  RegulationItemsResponse,
  RegulationRefreshResponse,
  RegulationSource,
  RegulationSourcesResponse,
} from "@/lib/types";

function formatDate(value: string | null | undefined): string {
  if (!value) return "unknown";
  return new Date(value).toLocaleString();
}

function freshness(source: RegulationSource): string {
  if (!source.enabled) return "disabled (needs setup)";
  if (!source.last_fetched_at) return "not yet fetched";
  return `last fetched ${formatDate(source.last_fetched_at)}`;
}

export default function RegulationPage() {
  const { ready } = useRequireAuth();
  const [user, setUser] = useState(getStoredUser());
  const [sources, setSources] = useState<RegulationSource[]>([]);
  const [sourceInfo, setSourceInfo] =
    useState<RegulationSourcesResponse | null>(null);
  const [items, setItems] = useState<RegulationItemsResponse | null>(null);
  const [itemType, setItemType] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [topic, setTopic] = useState("");
  const [search, setSearch] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] =
    useState<RegulationRefreshResponse | null>(null);

  useEffect(() => {
    setUser(getStoredUser());
  }, [ready]);

  async function loadSources() {
    try {
      const data = await apiFetch<RegulationSourcesResponse>(
        "/regulation/sources",
      );
      setSourceInfo(data);
      setSources(data.sources);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load sources");
    }
  }

  async function loadItems(params: {
    type: string;
    jurisdiction: string;
    topic: string;
    query: string;
    offset: number;
  }) {
    const searchParams = new URLSearchParams();
    if (params.type) searchParams.set("item_type", params.type);
    if (params.jurisdiction) searchParams.set("jurisdiction", params.jurisdiction);
    if (params.topic) searchParams.set("topic", params.topic);
    if (params.query) searchParams.set("q", params.query);
    searchParams.set("limit", "20");
    searchParams.set("offset", String(params.offset));
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<RegulationItemsResponse>(
        `/regulation/items?${searchParams.toString()}`,
      );
      setItems(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load items");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!ready) return;
    loadSources();
    loadItems({ type: itemType, jurisdiction, topic, query: submittedQuery, offset });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, itemType, jurisdiction, topic, submittedQuery, offset]);

  async function handleRefresh(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const data = await apiFetch<RegulationRefreshResponse>(
        "/regulation/refresh",
        { method: "POST" },
      );
      setRefreshResult(data);
      await loadItems({
        type: itemType,
        jurisdiction,
        topic,
        query: submittedQuery,
        offset,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  if (!ready) return null;

  const isAdmin = user?.role === "admin";

  return (
    <main className="container">
      <header>
        <h1>Regulation & News</h1>
        <p>
          Aggregated regulatory and news items from curated public sources.
          Original titles and links are preserved; short summaries are clearly
          labeled and none of this is legal advice.
        </p>
      </header>

      {items && (
        <div className="alert">
          <ul className="muted">
            {items.disclaimers.map((disclaimer) => (
              <li key={disclaimer}>{disclaimer}</li>
            ))}
            <li>Informational feed only &mdash; not legal advice.</li>
          </ul>
        </div>
      )}

      {isAdmin && (
        <section className="actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing sources..." : "Refresh sources now"}
          </button>
          <span className="muted small-note">
            Manual refresh is admin-gated; it fetches the curated public feeds
            and records an audited run.
          </span>
        </section>
      )}

      {refreshResult && (
        <section className="card">
          <h2>Latest refresh</h2>
          <p className={`badge ${refreshResult.status === "success" ? "" : "error"}`}>
            {refreshResult.status}
          </p>
          {refreshResult.stats.note && (
            <p className="muted">{refreshResult.stats.note}</p>
          )}
          <table className="table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Inserted</th>
                <th>Updated</th>
                <th>Unchanged</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {refreshResult.stats.sources.map((stat) => (
                <tr key={stat.source}>
                  <td>{stat.source}</td>
                  <td>{stat.inserted}</td>
                  <td>{stat.updated}</td>
                  <td>{stat.unchanged}</td>
                  <td>
                    {stat.failed ? (
                      <span className="muted">{stat.failed}</span>
                    ) : (
                      "ok"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {refreshResult.stats.failed_sources > 0 && (
            <p className="muted small-note">
              Failed sources did not affect stored data or other workflows; try
              again later. PostgreSQL inventory/marketplace are unaffected.
            </p>
          )}
        </section>
      )}

      <form
        className="filters-bar"
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setSubmittedQuery(search);
        }}
      >
        <label>
          Type
          <select
            value={itemType}
            onChange={(event) => {
              setOffset(0);
              setItemType(event.target.value);
            }}
          >
            <option value="">All types</option>
            <option value="regulation">Regulation</option>
            <option value="news">News</option>
          </select>
        </label>
        <label>
          Jurisdiction
          <select
            value={jurisdiction}
            onChange={(event) => {
              setOffset(0);
              setJurisdiction(event.target.value);
            }}
          >
            <option value="">All jurisdictions</option>
            {sourceInfo?.supported_jurisdictions.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label>
          Topic
          <select
            value={topic}
            onChange={(event) => {
              setOffset(0);
              setTopic(event.target.value);
            }}
          >
            <option value="">All topics</option>
            {sourceInfo?.supported_topics.map((topicOption) => (
              <option key={topicOption} value={topicOption}>
                {topicOption}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search titles and summaries"
          />
        </label>
        <button type="submit" className="btn">
          Search
        </button>
      </form>

      {error && <div className="alert error">{error}</div>}
      {loading && <div className="muted">Loading regulation and news items...</div>}

      {items && !loading && (
        <>
          <p className="result-count muted">
            {items.total === 0
              ? "No items match these filters yet. If sources have not been refreshed, ask an admin to run Refresh sources now."
              : `${items.total} item(s) — showing ${items.offset + 1}–${Math.min(items.offset + items.limit, items.total)}`}
          </p>

          {items.items.map((item) => (
            <article key={item.id} className="card match-card">
              <div className="match-header">
                <div>
                  <span className="chip">{item.item_type}</span>
                  <span className="chip">{item.jurisdiction}</span>
                  <span className="badge">{item.summary_label}</span>
                </div>
              </div>
              <h2>
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.title}
                </a>
              </h2>
              {item.summary && <p>{item.summary}</p>}
              {item.topics.length > 0 && (
                <div className="breakdown">
                  {item.topics.map((topicTag) => (
                    <span key={topicTag} className="breakdown-chip">
                      {topicTag}
                    </span>
                  ))}
                </div>
              )}
              <p className="muted small-note">
                {item.source_name}
                {" · published "}
                {item.published_at ? formatDate(item.published_at) : "unknown date"}
                {" · fetched "}
                {item.fetched_at ? formatDate(item.fetched_at) : "unknown"}
              </p>
              {item.summary_kind === "ai_generated" && (
                <p className="muted small-note">
                  AI-generated summary — informational only, may omit details,
                  and is not legal advice. The original source above is
                  authoritative.
                </p>
              )}
            </article>
          ))}

          {items.total > items.limit && (
            <div className="pagination">
              <button
                type="button"
                className="btn"
                onClick={() => setOffset(Math.max(0, items.offset - items.limit))}
                disabled={items.offset === 0}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => setOffset(items.offset + items.limit)}
                disabled={items.offset + items.limit >= items.total}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}

      <section className="card">
        <h2>Sources</h2>
        <p className="muted small-note">
          Curated public sources (registry {sourceInfo?.registry_version ?? "…"}).
          Sources are marked stale when their newest item is older than{" "}
          {sourceInfo?.stale_after_days ?? "…"} days. Available feeds are
          keyless; none use paid providers, and no credentials are stored.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Jurisdiction</th>
              <th>Kind</th>
              <th>Freshness</th>
              <th>Newest item</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.key}>
                <td>
                  <a href={source.homepage_url} target="_blank" rel="noopener noreferrer">
                    {source.name}
                  </a>
                  {source.stale && (
                    <span className="badge">stale</span>
                  )}
                  {source.needs_setup && (
                    <span className="chip">needs setup</span>
                  )}
                </td>
                <td>{source.jurisdiction}</td>
                <td>{source.kind}</td>
                <td>{freshness(source)}</td>
                <td>{formatDate(source.last_item_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details>
          <summary>Source terms & attribution notes</summary>
          <ul>
            {sources.map((source) => (
              <li key={source.key} className="muted small-note">
                <strong>{source.name}:</strong> {source.terms_note}
              </li>
            ))}
          </ul>
        </details>
      </section>
    </main>
  );
}
