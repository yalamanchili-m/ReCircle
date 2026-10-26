"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type {
  GraphExploreResponse,
  GraphStatusResponse,
  GraphSyncResponse,
} from "@/lib/types";

function GraphPageContent() {
  const { ready, user } = useRequireAuth();
  const isAdmin = user?.role === "admin";
  const [status, setStatus] = useState<GraphStatusResponse | null>(null);
  const [exploreNodeId, setExploreNodeId] = useState("");
  const [explore, setExplore] = useState<GraphExploreResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const loadStatus = useCallback(() => {
    if (!ready) return;
    apiFetch<GraphStatusResponse>("/graph/status")
      .then(setStatus)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load graph status"),
      );
  }, [ready]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function runSync() {
    setSyncing(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiFetch<GraphSyncResponse>("/graph/sync", { method: "POST" });
      setMessage(
        `Sync complete: ${result.stats.organizations} organizations, ` +
          `${result.stats.listings} listings, ${result.stats.requirements} requirements, ` +
          `${result.stats.inferred_matches} inferred matches projected.`,
      );
      loadStatus();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Graph sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function runExplore(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setExplore(null);
    try {
      const result = await apiFetch<GraphExploreResponse>(
        `/graph/explore?node_id=${encodeURIComponent(exploreNodeId.trim())}`,
      );
      setExplore(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Graph exploration failed");
    }
  }

  if (!ready) {
    return (
      <main className="container">
        <p className="muted">Loading...</p>
      </main>
    );
  }

  return (
    <main className="container">
      <header>
        <h1>Knowledge graph</h1>
        <p>
          Neo4j projection of PostgreSQL facts and curated taxonomy edges. Every
          edge carries provenance; inferred relationships are clearly marked as
          non-factual.
        </p>
      </header>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <div className="card">
        <h2>Status</h2>
        {status ? (
          <>
            <p>
              Neo4j configured: <strong>{status.neo4j_configured ? "yes" : "no"}</strong>{" "}
              &middot; Connected: <strong>{status.connected ? "yes" : "no"}</strong>
            </p>
            {status.counts && (
              <p className="detail">
                Organizations: {status.counts.Organization ?? 0} &middot; Listings:{" "}
                {status.counts.Listing ?? 0} &middot; Requirements:{" "}
                {status.counts.Requirement ?? 0} &middot; Material types:{" "}
                {status.counts.MaterialType ?? 0}
              </p>
            )}
            {status.last_sync && (
              <p className="muted">
                Last sync: {status.last_sync.status} &middot;{" "}
                {status.last_sync.projection_version}
                {status.last_sync.error ? ` — ${status.last_sync.error}` : ""}
              </p>
            )}
          </>
        ) : (
          <p className="muted">Loading status...</p>
        )}
        {isAdmin && (
          <button type="button" className="btn btn-primary" onClick={runSync} disabled={syncing}>
            {syncing ? "Syncing..." : "Run graph sync"}
          </button>
        )}
      </div>

      <div className="card">
        <h2>Explore</h2>
        <p className="muted">
          Look up a node by stable id, e.g. <code>org:&lt;uuid&gt;</code>,{" "}
          <code>listing:&lt;uuid&gt;</code> or <code>material:plastics-pet</code>.
        </p>
        <form onSubmit={runExplore} className="filters">
          <input
            type="text"
            value={exploreNodeId}
            onChange={(e) => setExploreNodeId(e.target.value)}
            placeholder="node id"
            required
            minLength={3}
          />
          <button type="submit" className="btn btn-primary" disabled={!exploreNodeId.trim()}>
            Explore
          </button>
        </form>

        {explore && !explore.connected && <p className="muted">{explore.note}</p>}
        {explore?.connected && explore.node && (
          <>
            <p className="detail">
              Labels: {explore.node.labels.join(", ")}
            </p>
            {explore.relationships.length === 0 ? (
              <p className="muted">No one-hop relationships.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Relationship</th>
                    <th>Provenance</th>
                    <th>Other node</th>
                  </tr>
                </thead>
                <tbody>
                  {explore.relationships.map((rel, index) => (
                    <tr key={`${rel.rel_type}-${index}`}>
                      <td>{rel.rel_type}</td>
                      <td>
                        <span
                          className={`provenance-badge ${
                            rel.rel_properties?.is_fact === false ? "provenance-inferred" : ""
                          }`}
                        >
                          {typeof rel.rel_properties?.provenance === "string"
                            ? rel.rel_properties.provenance
                            : "unknown"}
                        </span>
                      </td>
                      <td>
                        {rel.other_labels.join(", ")} —{" "}
                        {typeof rel.other?.name === "string"
                          ? rel.other.name
                          : typeof rel.other?.title === "string"
                            ? rel.other.title
                            : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </main>
  );
}

export default function GraphPage() {
  return <GraphPageContent />;
}
