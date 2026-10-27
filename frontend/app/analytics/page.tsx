"use client";

import { useCallback, useEffect, useState } from "react";

import { apiDownloadFile, apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import {
  KMeansResponse,
  MarketplaceMetrics,
} from "@/lib/types";

const PATHWAY_LABELS: Record<string, string> = {
  reuse: "Reuse",
  recycle: "Recycle",
  upcycle: "Upcycle",
  remanufacture: "Remanufacture",
};

function AnalyticsContent() {
  const { ready } = useRequireAuth();
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [category, setCategory] = useState("");
  const [industry, setIndustry] = useState("");
  const [metrics, setMetrics] = useState<MarketplaceMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [subject, setSubject] = useState<"listings" | "requirements">("listings");
  const [k, setK] = useState("");
  const [clusterCategory, setClusterCategory] = useState("");
  const [kmeans, setKmeans] = useState<KMeansResponse | null>(null);
  const [clusterLoading, setClusterLoading] = useState(false);

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (periodFrom) params.set("period_from", periodFrom);
      if (periodTo) params.set("period_to", periodTo);
      if (category) params.set("category", category);
      if (industry.trim()) params.set("industry", industry.trim());
      const query = params.toString() ? `?${params.toString()}` : "";
      const body = await apiFetch<MarketplaceMetrics>(
        `/analytics/marketplace${query}`,
      );
      setMetrics(body);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load metrics");
    } finally {
      setMetricsLoading(false);
    }
  }, [periodFrom, periodTo, category, industry]);

  useEffect(() => {
    if (ready) void loadMetrics();
  }, [ready, loadMetrics]);

  const runKmeans = useCallback(async () => {
    setClusterLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ subject });
      if (k) params.set("k", String(Number(k)));
      if (clusterCategory) params.set("category", clusterCategory);
      const body = await apiFetch<KMeansResponse>(
        `/analytics/kmeans?${params.toString()}`,
        { method: "POST" },
      );
      setKmeans(body);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Clustering failed");
    } finally {
      setClusterLoading(false);
    }
  }, [subject, k, clusterCategory]);

  async function handleExport() {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (periodFrom) params.set("period_from", periodFrom);
      if (periodTo) params.set("period_to", periodTo);
      if (category) params.set("category", category);
      if (industry.trim()) params.set("industry", industry.trim());
      const query = params.toString() ? `?${params.toString()}` : "";
      const { blob, filename } = await apiDownloadFile(
        `/analytics/marketplace/export${query}`,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed");
    }
  }

  if (!ready) {
    return (
      <main className="container">
        <p className="muted">Loading...</p>
      </main>
    );
  }

  const m = metrics?.metrics;

  return (
    <main className="container">
      <header>
        <h1>Marketplace Analytics</h1>
        <p>
          Database-backed marketplace metrics and exploratory K-means
          clustering. Counts are activity signals, never verified outcomes,
          and clusters are explicitly not authoritative material classes.
        </p>
      </header>

      <div className="filters card">
        <label>
          From
          <input
            type="date"
            value={periodFrom}
            onChange={(e) => setPeriodFrom(e.target.value)}
          />
        </label>
        <label>
          To
          <input
            type="date"
            value={periodTo}
            onChange={(e) => setPeriodTo(e.target.value)}
          />
        </label>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {[
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
          ].map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Industry (passport-based filter)"
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-primary"
          onClick={loadMetrics}
          disabled={metricsLoading}
        >
          {metricsLoading ? "Loading..." : "Refresh"}
        </button>
        <button type="button" className="btn" onClick={handleExport}>
          Export CSV (aggregates)
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {m && m.warnings.length > 0 && (
        <ul className="warnings">
          {m.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {m && (
        <>
          <section className="card">
            <h2>
              Listings by status
              {metrics?.version && ` · ${metrics.version}`}
            </h2>
            <p className="muted small-note">
              Window {metrics?.period.from} to {metrics?.period.to} —{" "}
              {metrics?.period.basis}
            </p>
            <div className="breakdown">
              {Object.entries(m.listings).map(([status, count]) => (
                <span key={status} className="breakdown-chip">
                  {status}: <strong>{count}</strong>
                </span>
              ))}
              {Object.keys(m.listings).length === 0 && (
                <span className="muted">No listings in this period.</span>
              )}
            </div>
          </section>

          <section className="card">
            <h2>Supply / demand by category (active, mass-normalized)</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Active listings</th>
                  <th>Supply (t)</th>
                  <th>Active requirements</th>
                  <th>Demand (t min)</th>
                </tr>
              </thead>
              <tbody>
                {m.supply_demand_rows.map((row) => (
                  <tr key={row.category}>
                    <td>{row.category}</td>
                    <td>{row.active_listings}</td>
                    <td>{row.active_listings_tonnes.toLocaleString()}</td>
                    <td>{row.active_requirements}</td>
                    <td>
                      {row.active_requirements_min_tonnes.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small-note">
              Non-mass quantities (litre/unit) are counted but never converted
              to tonnes (marked excluded per row).
            </p>
          </section>

          <section className="card">
            <h2>Geographic distribution</h2>
            {m.geography.available ? (
              <>
                <div className="breakdown">
                  {m.geography.rows.map((row) => (
                    <span key={row.region} className="breakdown-chip">
                      {row.region}: <strong>{row.active_listings}</strong>
                    </span>
                  ))}
                </div>
                <p className="muted small-note">
                  Region coverage: {(m.geography.coverage * 100).toFixed(0)}%
                </p>
              </>
            ) : (
              <p className="muted small-note">{m.geography.reason}</p>
            )}
          </section>

          <section className="card">
            <h2>Match &amp; transaction activity</h2>
            <div className="breakdown">
              {Object.entries(m.match_activity).map(([key, value]) => (
                <span key={key} className="breakdown-chip">
                  {key.replace(/_/g, " ")}: <strong>{value}</strong>
                </span>
              ))}
            </div>
          </section>

          <section className="card">
            <h2>Feasible recovery pathways (curated templates)</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Count</th>
                  <th>Pathways</th>
                </tr>
              </thead>
              <tbody>
                {m.pathway_rows.map((row) => (
                  <tr key={row.category}>
                    <td>{row.category}</td>
                    <td>{row.feasible_pathway_count}</td>
                    <td>
                      {row.feasible_pathways
                        .map((p) => PATHWAY_LABELS[p] ?? p)
                        .join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2>Monthly activity (only when date coverage supports it)</h2>
            {m.time_series.available ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th>Listings</th>
                    <th>Requirements</th>
                    <th>Completed transactions</th>
                  </tr>
                </thead>
                <tbody>
                  {m.time_series.rows.map((row) => (
                    <tr key={row.month}>
                      <td>{row.month}</td>
                      <td>{row.listings_created}</td>
                      <td>{row.requirements_created}</td>
                      <td>{row.transactions_completed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">{m.time_series.reason}</p>
            )}
          </section>

          <section className="card">
            <details>
              <summary>Limitations</summary>
              <ul>
                {metrics?.limitations.map((item) => (
                  <li key={item} className="muted">
                    {item}
                  </li>
                ))}
              </ul>
            </details>
          </section>
        </>
      )}

      <section className="card" style={{ flexDirection: "column", alignItems: "stretch" }}>
        <h2>Exploratory K-means clustering</h2>
        <p className="muted small-note">
          Deterministic (farthest-first init, no randomness). Identifiers,
          timestamps and ownership are excluded from the feature set.
          Insufficient samples are reported instead of clustered.
        </p>
        <div className="filters" style={{ padding: 0 }}>
          <select
            value={subject}
            onChange={(e) => setSubject(e.target.value as "listings" | "requirements")}
          >
            <option value="listings">Material clusters (listings)</option>
            <option value="requirements">Demand patterns (requirements)</option>
          </select>
          <select
            value={clusterCategory}
            onChange={(e) => setClusterCategory(e.target.value)}
          >
            <option value="">All categories</option>
            {[
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
            ].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={2}
            max={6}
            placeholder="k (blank = auto)"
            value={k}
            onChange={(e) => setK(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={runKmeans}
            disabled={clusterLoading}
          >
            {clusterLoading ? "Clustering..." : "Run clustering"}
          </button>
        </div>

        {kmeans?.insufficient_data && (
          <div className="alert">
            <strong>Insufficient data.</strong> {kmeans.empty_state}
          </div>
        )}

        {kmeans && !kmeans.insufficient_data && kmeans.stats && (
          <>
            <p className="muted small-note">
              k={kmeans.k} ({kmeans.k_default_rule}) over {kmeans.sample_count}{" "}
              samples &middot; result {kmeans.result_version} &middot;{" "}
              {kmeans.stats.iterations} iterations &middot; inertia{" "}
              {kmeans.stats.inertia}
              {kmeans.stats.silhouette !== null &&
                ` &middot; silhouette ${kmeans.stats.silhouette}`}
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Cluster</th>
                  <th>Size</th>
                  <th>Share</th>
                  <th>Dominant category</th>
                  <th>Most distinguishing feature</th>
                </tr>
              </thead>
              <tbody>
                {kmeans.stats.clusters.map((cluster, index) => (
                  <tr key={cluster.cluster}>
                    <td>#{cluster.cluster}</td>
                    <td>{cluster.size}</td>
                    <td>{(cluster.share_of_sample * 100).toFixed(1)}%</td>
                    <td>
                      {cluster.dominant_category} (
                      {(cluster.dominant_category_share * 100).toFixed(0)}%)
                    </td>
                    <td className="muted">
                      {kmeans.stats?.centroid_highlights[index]?.feature} (
                      {kmeans.stats?.centroid_highlights[index]?.centroid_delta})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {kmeans.sampling_summary.warnings.length > 0 && (
              <ul className="warnings">
                {kmeans.sampling_summary.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
          </>
        )}

        {kmeans && (
          <details>
            <summary>Method, feature schema &amp; disclaimers</summary>
            <p className="muted small-note">
              Algorithm {kmeans.versions.algorithm} &middot; features{" "}
              {kmeans.versions.feature_schema} &middot; run{" "}
              {kmeans.run_id.slice(0, 8)}
            </p>
            <ul className="chip-list">
              {kmeans.feature_schema.map((feature) => (
                <li key={feature.feature} className="chip">
                  {feature.feature} ({feature.kind}
                  {feature.weight ? `, weight ${feature.weight}` : ""})
                </li>
              ))}
            </ul>
            <ul>
              {kmeans.disclaimers.map((item) => (
                <li key={item} className="muted">
                  {item}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </main>
  );
}

export default function AnalyticsPage() {
  return <AnalyticsContent />;
}
