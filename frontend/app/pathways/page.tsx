"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type {
  Explanation,
  PathwayCandidate,
  PathwayEvaluation,
} from "@/lib/types";

const CRITERION_LABELS: Record<string, string> = {
  environmental_impact: "Environmental impact",
  distance: "Distance",
  cost: "Cost",
  demand: "Demand",
  feasibility: "Feasibility",
};

function WhyPanel({ explanation }: { explanation: Explanation }) {
  return (
    <div className="explanation-panel">
      <p className="muted small-note">
        {explanation.subject_type} &middot; {explanation.subject_version} &middot;
        method {explanation.method}
      </p>
      <ul className="contribution-list">
        {explanation.contributions.map((contribution) => (
          <li key={contribution.feature}>
            <span className="contribution-feature">
              {CRITERION_LABELS[contribution.feature] ?? contribution.feature}
            </span>
            <span className="contribution-value">
              {contribution.value} {contribution.unit}
              {contribution.share_of_signal > 0
                ? ` · ${(contribution.share_of_signal * 100).toFixed(1)}%`
                : ""}
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

function PathwaysContent() {
  const { ready } = useRequireAuth();
  const [listings, setListings] = useState<
    { id: string; title: string; category: string }[]
  >([]);
  const [listingId, setListingId] = useState("");
  const [profile, setProfile] = useState("default");
  const [profiles, setProfiles] = useState<string[]>(["default"]);
  const [destination, setDestination] = useState("");
  const [result, setResult] = useState<PathwayEvaluation | null>(null);
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({});
  const [openExplain, setOpenExplain] = useState<Record<string, boolean>>({});
  const [explainBusy, setExplainBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    apiFetch<{ items: { id: string; title: string; category: string }[] }>(
      "/marketplace/listings?page_size=100",
    )
      .then((data) => setListings(data.items ?? []))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load listings"),
      );
    apiFetch<{ default: string; profiles: string[] }>("/pathways/profiles")
      .then((data) => {
        const keys = Object.keys(data.profiles ?? {});
        setProfiles(keys.length ? keys : ["default"]);
        setProfile(keys.includes("default") ? "default" : (keys[0] ?? "default"));
      })
      .catch(() => setProfiles(["default"]));
  }, [ready]);

  const evaluate = useCallback(async () => {
    if (!listingId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setExplanations({});
    setOpenExplain({});
    try {
      const data = await apiFetch<PathwayEvaluation>("/pathways/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          listing_id: listingId,
          profile,
          ...(destination.trim() ? { destination_region: destination.trim() } : {}),
        }),
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Pathway evaluation failed");
    } finally {
      setLoading(false);
    }
  }, [listingId, profile, destination]);

  const explain = useCallback(
    async (candidate: PathwayCandidate) => {
      if (!result) return;
      if (explanations[candidate.pathway]) {
        setOpenExplain((prev) => ({
          ...prev,
          [candidate.pathway]: !prev[candidate.pathway],
        }));
        return;
      }
      setExplainBusy(candidate.pathway);
      setError(null);
      try {
        const data = await apiFetch<Explanation>(
          `/explain/pathway?listing_id=${result.listing_id}&pathway=${candidate.pathway}&profile=${result.profile}`,
        );
        setExplanations((prev) => ({ ...prev, [candidate.pathway]: data }));
        setOpenExplain((prev) => ({ ...prev, [candidate.pathway]: true }));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Explanation failed");
      } finally {
        setExplainBusy(null);
      }
    },
    [result, explanations],
  );

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
        <h1>Recovery pathways</h1>
        <p>
          Deterministic Weighted Sum Model ranking of reuse / recycle / upcycle /
          remanufacture for a listing. Hard feasibility rules are applied before
          any scoring and can never be overridden. Scores are curated
          decision-support proxies, not measured carbon data.
        </p>
      </header>

      <div className="filters card">
        <select value={listingId} onChange={(e) => setListingId(e.target.value)}>
          <option value="">
            {listings.length ? "Select a listing" : "No listings available"}
          </option>
          {listings.map((listing) => (
            <option key={listing.id} value={listing.id}>
              {listing.title} ({listing.category})
            </option>
          ))}
        </select>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          {profiles.map((key) => (
            <option key={key} value={key}>
              Profile: {key}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Destination region (optional)"
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-primary"
          onClick={evaluate}
          disabled={!listingId || loading}
        >
          {loading ? "Evaluating..." : "Rank pathways"}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}

      {result && (
        <>
          <section className="card">
            <h2>Ranked pathways</h2>
            <p className="muted small-note">
              Optimizer {result.versions?.["optimizer"]} &middot; templates{" "}
              {result.versions?.["templates"]} &middot; {result.runtime_ms} ms
              &middot; profile {result.profile}
              {result.destination_region
                ? ` &middot; destination ${result.destination_region}`
                : ""}
            </p>
            {Object.keys(result.missing_data).length > 0 && (
              <ul className="warnings">
                {Object.entries(result.missing_data).map(([criterion, note]) => (
                  <li key={criterion}>
                    <strong>{criterion}</strong> dropped with renormalization: {note}
                  </li>
                ))}
              </ul>
            )}
            {result.ranked.map((candidate, index) => (
              <div className="card match-card" key={candidate.pathway}>
                <div className="match-header">
                  <div>
                    <h3>
                      #{index + 1} {candidate.label}
                    </h3>
                    <div className="detail">
                      Steps: {candidate.steps.join(" → ")} &middot;{" "}
                      {candidate.transport_legs} transport leg
                      {candidate.transport_legs === 1 ? "" : "s"}
                    </div>
                  </div>
                  <div className="score-box">
                    <span className="score-number">{candidate.score.toFixed(3)}</span>
                    <span className="score-denominator">WSM score</span>
                  </div>
                </div>

                <div className="breakdown">
                  {Object.entries(candidate.weighted_contributions).map(
                    ([criterion, value]) => (
                      <span
                        key={criterion}
                        className={`breakdown-chip ${value <= 0 ? "chip-zero" : ""}`}
                      >
                        {CRITERION_LABELS[criterion] ?? criterion}:{" "}
                        <strong>{value.toFixed(3)}</strong>
                      </span>
                    ),
                  )}
                  {candidate.missing_criteria.length > 0 && (
                    <span className="breakdown-chip chip-zero">
                      Missing data:{" "}
                      {candidate.missing_criteria
                        .map((c) => CRITERION_LABELS[c] ?? c)
                        .join(", ")}
                    </span>
                  )}
                </div>

                <button
                  type="button"
                  className="btn"
                  onClick={() => explain(candidate)}
                  disabled={explainBusy === candidate.pathway}
                >
                  {explainBusy === candidate.pathway
                    ? "Explaining..."
                    : openExplain[candidate.pathway]
                      ? "Hide 'Why this pathway?'"
                      : "Why this pathway?"}
                </button>
                {openExplain[candidate.pathway] &&
                  explanations[candidate.pathway] && (
                    <WhyPanel explanation={explanations[candidate.pathway]} />
                  )}
              </div>
            ))}
          </section>

          {result.rejected.length > 0 && (
            <section className="card">
              <h2>Excluded before ranking (hard feasibility rules)</h2>
              <ul>
                {result.rejected.map((row) => (
                  <li key={row.pathway}>
                    <strong>{row.pathway}</strong>: {row.reason}
                  </li>
                ))}
              </ul>
              <p className="muted small-note">
                Feasibility can never be overridden by scores. Ask
                &ldquo;Why this pathway?&rdquo; via{" "}
                <code>/api/explain/pathway?pathway={result.rejected[0]?.pathway}</code>{" "}
                for the gate explanation.
              </p>
            </section>
          )}

          <section className="card">
            <details>
              <summary>Assumptions behind these scores</summary>
              <ul>
                {result.assumptions.map((assumption) => (
                  <li key={assumption} className="muted">
                    {assumption}
                  </li>
                ))}
              </ul>
            </details>
            <details>
              <summary>Sensitivity (±25% weight perturbation)</summary>
              <ul>
                {result.sensitivity.map((row) => (
                  <li key={row.criterion} className="muted">
                    {row.criterion}: gap {row.score_gap} vs max perturbation effect{" "}
                    {row.max_perturbation_effect} — top rank{" "}
                    {row.top_rank_stable ? "stable" : "could flip"}
                  </li>
                ))}
              </ul>
            </details>
          </section>
        </>
      )}

      {!result && !loading && (
        <div className="card empty">
          <p>
            Select a listing and rank its feasible recovery pathways. Every score
            is a deterministic, explainable decision-support signal.
          </p>
        </div>
      )}
    </main>
  );
}

export default function PathwaysPage() {
  return <PathwaysContent />;
}
