"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type { MatchCandidate, MatchRunResponse, Requirement } from "@/lib/types";

const CRITERION_LABELS: Record<string, string> = {
  category: "Category (40)",
  quantity: "Quantity (25)",
  quality: "Quality (20)",
  location: "Location (10)",
  price: "Price (5)",
};

function MatchesContent() {
  const searchParams = useSearchParams();
  const { ready } = useRequireAuth(["buyer", "admin"]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [selected, setSelected] = useState<string>(searchParams.get("requirement") ?? "");
  const [results, setResults] = useState<MatchCandidate[] | null>(null);
  const [persist, setPersist] = useState(false);
  const [persisted, setPersisted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!ready) return;
    apiFetch<Requirement[]>("/requirements?status=active")
      .then((items) => {
        setRequirements(items);
        if (!selected && items.length > 0) setSelected(items[0].id);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load requirements"),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  const run = useCallback(async () => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const runResult = await apiFetch<MatchRunResponse>(
        `/requirements/${selected}/matches${persist ? "?persist=true" : ""}`,
        { method: "POST" },
      );
      setResults(runResult.results);
      setPersisted(runResult.persisted);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Matching failed");
    } finally {
      setLoading(false);
    }
  }, [selected, persist]);

  return (
    <main className="container">
      <header>
        <h1>Matches</h1>
        <p>
          Ranked active listings for a requirement. Scores are deterministic
          decision-support signals, not guarantees of suitability.
        </p>
      </header>

      <div className="filters card">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {requirements.length === 0 && <option value="">No requirements available</option>}
          {requirements.map((requirement) => (
            <option key={requirement.id} value={requirement.id}>
              {requirement.title} ({requirement.category})
            </option>
          ))}
        </select>
        <label className="persist-toggle">
          <input
            type="checkbox"
            checked={persist}
            onChange={(e) => setPersist(e.target.checked)}
          />
          Save snapshot
        </label>
        <button type="button" className="btn btn-primary" onClick={run} disabled={!selected || loading}>
          {loading ? "Matching..." : "Generate matches"}
        </button>
        <Link href="/requirements" className="btn">
          Manage requirements
        </Link>
      </div>

      {error && <div className="alert error">{error}</div>}
      {persisted && <div className="alert success">Match snapshot saved for review later.</div>}

      {results && results.length === 0 && (
        <div className="card empty">
          <p>No compatible active listings found for this requirement.</p>
          <p className="muted">Category-incompatible listings are excluded entirely.</p>
        </div>
      )}

      {results &&
        results.map((candidate) => (
          <div className="card match-card" key={candidate.listing_id}>
            <div className="match-header">
              <div>
                <h2>
                  <Link href={`/marketplace/${candidate.listing_id}`} className="table-link">
                    {candidate.title}
                  </Link>
                </h2>
                <div className="detail">
                  {candidate.organization_name} &middot; {candidate.city}
                  {candidate.region ? `, ${candidate.region}` : ""} &middot;{" "}
                  {candidate.quantity} {candidate.unit}
                  {candidate.price_per_unit
                    ? ` &middot; ${candidate.price_per_unit} ${candidate.currency}/${candidate.unit}`
                    : ""}
                </div>
              </div>
              <div className="score-box">
                <span className="score-number">{candidate.score}</span>
                <span className="score-denominator">/ {candidate.max_applicable}</span>
              </div>
            </div>

            <div className="breakdown">
              {Object.entries(candidate.score_breakdown).map(([key, value]) => (
                <span key={key} className={`breakdown-chip ${value === 0 ? "chip-zero" : ""}`}>
                  {CRITERION_LABELS[key] ?? key}: <strong>{value}</strong>
                </span>
              ))}
              <span className="breakdown-chip">
                Material fit: <strong>{candidate.material_fit}%</strong>
              </span>
              <span className="breakdown-chip">
                KNN: <strong>{candidate.knn_score}</strong>
              </span>
            </div>

            <p className="explanation">{candidate.explanation}</p>
            <p className="muted">
              Algorithm {candidate.algorithm_version} — decision support only,
              not proof of chemical, legal, or process safety.
            </p>

            {candidate.warnings.length > 0 && (
              <ul className="warnings">
                {candidate.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
    </main>
  );
}

export default function MatchesPage() {
  return (
    <Suspense fallback={<main className="container"><p className="muted">Loading...</p></main>}>
      <MatchesContent />
    </Suspense>
  );
}