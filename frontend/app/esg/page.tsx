"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { apiDownloadFile, apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type { EsgDashboard, Explanation } from "@/lib/types";

function ExplanationDetails({ explanation }: { explanation: Explanation }) {
  return (
    <div className="explanation-panel">
      <p className="muted small-note">
        {explanation.subject_type} &middot; {explanation.subject_version} &middot;
        method {explanation.method}
      </p>
      <ul className="contribution-list">
        {explanation.contributions.map((contribution) => (
          <li key={contribution.feature}>
            <span className="contribution-feature">{contribution.feature}</span>
            <span className="contribution-value">
              {contribution.value} {contribution.unit}
            </span>
            {contribution.detail && (
              <span className="contribution-detail muted">{contribution.detail}</span>
            )}
          </li>
        ))}
      </ul>
      <details>
        <summary>Caveats &amp; method notes</summary>
        <ul>
          {explanation.caveats.map((caveat) => (
            <li key={caveat} className="muted">
              {caveat}
            </li>
          ))}
          <li className="muted">{explanation.causation_note}</li>
        </ul>
      </details>
    </div>
  );
}

export default function EsgPage() {
  const { ready } = useRequireAuth();
  const [dashboard, setDashboard] = useState<EsgDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [exporting, setExporting] = useState(false);
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({});
  const [openExplain, setOpenExplain] = useState<Record<string, boolean>>({});
  const [explainBusy, setExplainBusy] = useState<string | null>(null);

  async function explainEstimate(recoveryRecordId: string) {
    if (explanations[recoveryRecordId]) {
      setOpenExplain((prev) => ({
        ...prev,
        [recoveryRecordId]: !prev[recoveryRecordId],
      }));
      return;
    }
    setExplainBusy(recoveryRecordId);
    setError(null);
    try {
      const data = await apiFetch<Explanation>(
        `/explain/impact/${recoveryRecordId}`,
      );
      setExplanations((prev) => ({ ...prev, [recoveryRecordId]: data }));
      setOpenExplain((prev) => ({ ...prev, [recoveryRecordId]: true }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Explanation failed");
    } finally {
      setExplainBusy(null);
    }
  }

  useEffect(() => {
    if (!ready) return;
    const params = new URLSearchParams();
    if (periodFrom) params.set("period_from", periodFrom);
    if (periodTo) params.set("period_to", periodTo);
    const query = params.toString() ? `?${params.toString()}` : "";
    setLoading(true);
    apiFetch<EsgDashboard>(`/esg/dashboard${query}`)
      .then(setDashboard)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load ESG data"),
      )
      .finally(() => setLoading(false));
  }, [ready, periodFrom, periodTo]);

  async function handleExport() {
    setError(null);
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (periodFrom) params.set("period_from", periodFrom);
      if (periodTo) params.set("period_to", periodTo);
      const query = params.toString() ? `?${params.toString()}` : "";
      const { blob, filename } = await apiDownloadFile(`/esg/export${query}`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="container">
      <header>
        <h1>ESG Analytics</h1>
        <p>
          Circular-economy metrics derived from transaction recovery outcomes and
          factor-based impact estimates. Estimated values are never presented as
          verified outcomes.
        </p>
      </header>

      <div className="filters-bar">
        <label>
          From
          <input
            type="date"
            value={periodFrom}
            onChange={(event) => setPeriodFrom(event.target.value)}
          />
        </label>
        <label>
          To
          <input
            type="date"
            value={periodTo}
            onChange={(event) => setPeriodTo(event.target.value)}
          />
        </label>
        <button type="button" className="btn" onClick={handleExport} disabled={exporting}>
          {exporting ? "Exporting..." : "Export CSV"}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <div className="muted">Loading ESG metrics...</div>}

      {dashboard && (
        <>
          {dashboard.coverage.recovery_record_count === 0 ? (
            <div className="alert">
              No recovery outcomes recorded for this period yet. Recovery records
              appear here once a matched transaction is completed with a recorded
              recovery outcome.
            </div>
          ) : (
            <>
              <div className="stats-grid">
                <div className="card stat">
                  <span className="stat-number">
                    {dashboard.metrics.mass_normalized.tonnes_recovered.toLocaleString(
                      undefined,
                      { maximumFractionDigits: 3 },
                    )}
                  </span>
                  <span className="stat-label">
                    Tonnes recovered (user-reported)
                  </span>
                </div>
                <div className="card stat">
                  <span className="stat-number">
                    ~
                    {dashboard.metrics.landfill_diverted.tonnes_estimate.toLocaleString(
                      undefined,
                      { maximumFractionDigits: 3 },
                    )}
                  </span>
                  <span className="stat-label">
                    Tonnes landfill-diverted (estimated)
                  </span>
                </div>
                <div className="card stat">
                  <span className="stat-number">
                    ~{dashboard.metrics.avoided_emissions.kg_co2e_estimate.toLocaleString()}
                  </span>
                  <span className="stat-label">kg CO2e avoided (estimated)</span>
                </div>
                <div className="card stat">
                  <span className="stat-number">
                    {dashboard.green_credit.points.toLocaleString()}
                  </span>
                  <span className="stat-label">
                    Green points (indicative, not official credits)
                  </span>
                </div>
              </div>

              <section className="card">
                <h2>Recovered quantity by unit (user-reported)</h2>
                <div className="breakdown">
                  {dashboard.metrics.recovered_by_unit.map((row) => (
                    <span key={row.unit} className="breakdown-chip">
                      <strong>{row.total.toLocaleString()}</strong> {row.unit} &middot;{" "}
                      {row.record_count} record{row.record_count === 1 ? "" : "s"}
                    </span>
                  ))}
                </div>
                <p className="muted small-note">
                  Quantities are grouped per unit and never summed across
                  incompatible units. {dashboard.metrics.mass_normalized.excluded_reason}
                </p>
              </section>

              <section className="card">
                <h2>Recovery routes</h2>
                {dashboard.metrics.recovery_route_breakdown.length === 0 ? (
                  <p className="muted">No recovery outcomes yet.</p>
                ) : (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Route</th>
                        <th>Records</th>
                        <th>Tonnes (normalized)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard.metrics.recovery_route_breakdown.map((row) => (
                        <tr key={row.recovery_route}>
                          <td>{row.recovery_route}</td>
                          <td>{row.record_count}</td>
                          <td>{row.tonnes_recovered.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="card">
                <h2>Recovery records (drill-down)</h2>
                <p className="muted small-note">
                  {dashboard.coverage["verified_count"]} verified &middot;{" "}
                  {dashboard.coverage["unverified_count"]} unverified &middot;{" "}
                  {dashboard.coverage["records_with_supported_estimate"]} with
                  supported estimates &middot;{" "}
                  {dashboard.coverage["records_without_supported_estimate"]} without
                </p>
                {dashboard.records.length === 0 ? (
                  <p className="muted">No records in this period.</p>
                ) : (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Material</th>
                        <th>Route</th>
                        <th>Recovered</th>
                        <th>Verification</th>
                        <th>Est. CO2e (kg)</th>
                        <th>Method</th>
                        <th>Explain</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard.records.map((record) => (
                        <Fragment key={record.recovery_record_id}>
                          <tr>
                            <td>{record.recorded_date ?? "-"}</td>
                            <td>{record.listing_title}</td>
                            <td>{record.recovery_route}</td>
                            <td>
                              {record.recovered_quantity.toLocaleString()} {record.unit}
                            </td>
                            <td>
                              <span
                                className={`badge status-${
                                  record.verification_status === "verified"
                                    ? "active"
                                    : "draft"
                                }`}
                              >
                                {record.verification_status}
                              </span>
                            </td>
                            <td>
                              {record.estimate?.supported
                                ? `~${record.estimate.avoided_co2e_kg?.toLocaleString()}`
                                : "unavailable"}
                            </td>
                            <td>
                              {record.estimate?.supported
                                ? record.estimate.factor_catalog_version
                                : (record.estimate?.unsupported_reason ??
                                  "no estimate stored")}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn btn-ghost"
                                onClick={() => explainEstimate(record.recovery_record_id)}
                                disabled={explainBusy === record.recovery_record_id}
                              >
                                {explainBusy === record.recovery_record_id
                                  ? "..."
                                  : openExplain[record.recovery_record_id]
                                    ? "Hide"
                                    : "Why?"}
                              </button>
                            </td>
                          </tr>
                          {openExplain[record.recovery_record_id] &&
                            explanations[record.recovery_record_id] && (
                              <tr>
                                <td colSpan={8}>
                                  <ExplanationDetails
                                    explanation={
                                      explanations[record.recovery_record_id]
                                    }
                                  />
                                </td>
                              </tr>
                            )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="card">
                <h2>Green credit (indicative visualization)</h2>
                <p>
                  <strong>{dashboard.green_credit.points.toLocaleString()} points</strong>{" "}
                  &mdash; {dashboard.green_credit.formula}
                </p>
                <ul>
                  {dashboard.green_credit.disclaimers.map((item) => (
                    <li key={item} className="muted">
                      {item}
                    </li>
                  ))}
                </ul>
              </section>

              <section className="card">
                <h2>Methods, sources &amp; limitations</h2>
                <p>
                  <span className="badge">estimated</span>{" "}
                  {dashboard.metrics.avoided_emissions.method} &middot; factor catalog{" "}
                  {dashboard.metrics.avoided_emissions.factor_catalog_version}
                  {dashboard.metrics.avoided_emissions.uncertainty && (
                    <>
                      {" "}
                      &middot; uncertainty range{" "}
                      ~
                      {dashboard.metrics.avoided_emissions.uncertainty.band_low_kg.toLocaleString()}{" "}
                      to{" "}
                      {dashboard.metrics.avoided_emissions.uncertainty.band_high_kg.toLocaleString()}{" "}
                      kg CO2e (
                      {dashboard.metrics.avoided_emissions.uncertainty.basis})
                    </>
                  )}
                </p>
                <p className="muted">
                  Source: {dashboard.metrics.avoided_emissions.factor_source}
                </p>
                <p className="muted">
                  Baseline: {dashboard.metrics.avoided_emissions.baseline_reference}
                </p>
                <ul>
                  {dashboard.limitations.map((item) => (
                    <li key={item} className="muted">
                      {item}
                    </li>
                  ))}
                </ul>
              </section>
            </>
          )}
        </>
      )}
    </main>
  );
}
