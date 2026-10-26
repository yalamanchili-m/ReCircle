"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type {
  SymbiosisOpportunity,
  SymbiosisResponse,
  SymbiosisEvaluationResponse,
} from "@/lib/types";

const CATEGORIES = [
  "",
  "metals",
  "plastics",
  "paper_cardboard",
  "wood",
  "glass",
  "textiles",
  "organics",
  "electronics",
  "chemicals",
  "other",
] as const;

function SymbiosisPageContent() {
  const { ready } = useRequireAuth();
  const [category, setCategory] = useState("");
  const [region, setRegion] = useState("");
  const [result, setResult] = useState<SymbiosisResponse | null>(null);
  const [evaluation, setEvaluation] = useState<SymbiosisEvaluationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const discover = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (category) params.set("category", category);
      if (region.trim()) params.set("region", region.trim());
      const data = await apiFetch<SymbiosisResponse>(
        `/symbiosis/opportunities?${params.toString()}`,
      );
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Discovery failed");
    } finally {
      setLoading(false);
    }
  }, [category, region]);

  useEffect(() => {
    if (!ready) return;
    apiFetch<SymbiosisEvaluationResponse>("/symbiosis/evaluation")
      .then(setEvaluation)
      .catch(() => setEvaluation(null));
  }, [ready]);

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
        <h1>Industrial symbiosis</h1>
        <p>
          Graph-based discovery of potential by-product exchanges between
          organizations. Every link is an <strong>inferred opportunity requiring
          validation</strong> — not a verified trade.
        </p>
      </header>

      {error && <div className="alert error">{error}</div>}

      <div className="filters card">
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((value) => (
            <option key={value || "all"} value={value}>
              {value || "All categories"}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          placeholder="Filter by region"
        />
        <button
          type="button"
          className="btn btn-primary"
          onClick={discover}
          disabled={loading}
        >
          {loading ? "Discovering..." : "Discover opportunities"}
        </button>
      </div>

      {result && (
        <>
          <div className="card">
            <h2>Graph snapshot</h2>
            <p className="detail">
              {result.graph.nodes} nodes &middot; {result.graph.edges} edges &middot;
              snapshot <code>{result.graph.snapshot_id}</code>
            </p>
            {result.graph.top_hubs.length > 0 && (
              <p className="muted">
                Top hubs (PageRank):{" "}
                {result.graph.top_hubs
                  .map((hub) => `${hub.node.replace("material:", "").replace("industry:", "")} (${hub.pagerank.toFixed(4)})`)
                  .join(", ")}
              </p>
            )}
            <p className="muted">
              Louvain clusters:{" "}
              {Object.entries(result.graph.clusters)
                .sort((a, b) => Number(a[0]) - Number(b[0]))
                .map(([id, size]) => `#${id}: ${size} nodes`)
                .join(" · ")}
            </p>
          </div>

          {result.opportunities.length === 0 ? (
            <div className="card empty">
              <p>No candidate symbiosis links found for these filters.</p>
            </div>
          ) : (
            result.opportunities.map((opportunity, index) => (
              <div className="card match-card" key={`${opportunity.listing_id}-${opportunity.requirement_id}-${index}`}>
                <div className="match-header">
                  <div>
                    <h2>
                      {opportunity.producer_organization_name} &rarr;{" "}
                      {opportunity.consumer_organization_name}
                    </h2>
                    <div className="detail">
                      {opportunity.listing_title} &rarr; {opportunity.requirement_title}{" "}
                      &middot; {opportunity.category}
                    </div>
                  </div>
                  <div className="score-box">
                    <span className="score-number">{(opportunity.confidence * 100).toFixed(0)}</span>
                    <span className="score-denominator">/ 100</span>
                  </div>
                </div>

                <div className="breakdown">
                  <span className="breakdown-chip">
                    Material fit: <strong>{(opportunity.material_fit * 100).toFixed(0)}%</strong>
                  </span>
                  <span className="breakdown-chip">
                    Availability: <strong>{(opportunity.availability * 100).toFixed(0)}%</strong>
                  </span>
                  <span className="breakdown-chip">
                    Graph proximity: <strong>{(opportunity.graph_proximity * 100).toFixed(0)}%</strong>
                  </span>
                  {opportunity.cluster_membership !== null && (
                    <span className="breakdown-chip">
                      Cluster: <strong>#{opportunity.cluster_membership}</strong>
                    </span>
                  )}
                </div>

                {opportunity.evidence.path_edges.length > 0 && (
                  <p className="explanation">
                    Supporting path (depth {opportunity.evidence.path_depth}):{" "}
                    {opportunity.evidence.path_edges
                      .map((edge) => `${edge.from} —${edge.rel_type}→ ${edge.to}`)
                      .join(" → ")}
                  </p>
                )}
                <p className="muted">
                  Version {result.run.versions.discovery} — inferred opportunity
                  requiring validation; graph proximity is structural, not proof of
                  suitability.
                </p>
              </div>
            ))
          )}

          <div className="card">
            <h2>Limitations</h2>
            <ul className="warnings">
              {result.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </div>
        </>
      )}

      {evaluation && (
        <div className="card">
          <h2>
            Algorithm verification{" "}
            <span className="muted">
              ({evaluation.evaluation_version}: {evaluation.passed}/{evaluation.total} passed)
            </span>
          </h2>
          <p className="muted">{evaluation.dataset}</p>
        </div>
      )}
    </main>
  );
}

export default function SymbiosisPage() {
  return <SymbiosisPageContent />;
}
