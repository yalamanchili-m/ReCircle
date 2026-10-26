"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type { MaterialPassport, PassportProvenance } from "@/lib/types";

const PROVENANCE_LABELS: Record<PassportProvenance, string> = {
  user_provided: "Provided",
  source_derived: "Derived",
  ai_inferred: "AI-suggested",
  unverified: "Unverified",
};

const FIELD_LABELS: Record<string, string> = {
  material_name: "Material name",
  composition: "Composition",
  grade: "Grade",
  condition: "Condition",
  contamination_notes: "Contamination notes",
  quantity: "Quantity",
  unit: "Unit",
  city: "City",
  region: "Region",
};

/**
 * Material Passport panel (blueprint Phase 3 / §4.1).
 *
 * Every attribute is labelled with its provenance — provided, derived,
 * AI-suggested, or unverified — so inferred values are never presented as
 * verified facts. Saving an edit creates a new version; the previous
 * version is superseded and requires fresh human review.
 */
export default function PassportPanel({ listingId }: { listingId: string }) {
  const [passport, setPassport] = useState<MaterialPassport | null>(null);
  const [missing, setMissing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [applications, setApplications] = useState("");
  const [industries, setIndustries] = useState("");
  const [pathways, setPathways] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setMissing(false);
    try {
      const result = await apiFetch<MaterialPassport>(`/listings/${listingId}/passport`);
      setPassport(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setMissing(true);
        setPassport(null);
      } else {
        setError(err instanceof ApiError ? err.message : "Failed to load passport");
      }
    }
  }, [listingId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate() {
    setBusy(true);
    setError(null);
    try {
      setPassport(
        await apiFetch<MaterialPassport>(`/listings/${listingId}/passport`, {
          method: "POST",
          body: JSON.stringify({}),
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create passport");
    } finally {
      setBusy(false);
    }
  }

  function beginEdit() {
    if (!passport) return;
    setApplications(passport.possible_applications.join(", "));
    setIndustries(passport.suitable_industries.join(", "));
    setPathways(passport.candidate_pathways.join(", "));
    setNotes(passport.notes ?? "");
    setEditing(true);
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const toList = (value: string) =>
        value
          .split(",")
          .map((entry) => entry.trim())
          .filter(Boolean);
      setPassport(
        await apiFetch<MaterialPassport>(`/listings/${listingId}/passport`, {
          method: "PATCH",
          body: JSON.stringify({
            possible_applications: toList(applications),
            suitable_industries: toList(industries),
            candidate_pathways: toList(pathways),
            notes: notes.trim() ? notes.trim() : null,
          }),
        }),
      );
      setEditing(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save passport");
    } finally {
      setBusy(false);
    }
  }

  async function handleReview(reviewStatus: "reviewed" | "unreviewed") {
    setBusy(true);
    setError(null);
    try {
      setPassport(
        await apiFetch<MaterialPassport>(`/listings/${listingId}/passport/review`, {
          method: "POST",
          body: JSON.stringify({ review_status: reviewStatus }),
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update review status");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <section className="card">
        <h2>Material Passport</h2>
        <div className="alert error">{error}</div>
      </section>
    );
  }

  if (missing) {
    return (
      <section className="card">
        <h2>Material Passport</h2>
        <p className="muted">
          No passport yet. Create one to record normalized attributes, possible
          applications, and provenance for this material.
        </p>
        <button type="button" className="btn btn-primary" onClick={handleCreate} disabled={busy}>
          Create passport
        </button>
      </section>
    );
  }

  if (!passport) {
    return (
      <section className="card">
        <h2>Material Passport</h2>
        <p className="muted">Loading passport...</p>
      </section>
    );
  }

  return (
    <section className="card">
      <div className="passport-header">
        <h2>Material Passport</h2>
        <p className="muted">
          Version {passport.version} &middot;{" "}
          <span className={`badge passport-review-${passport.review_status}`}>
            {passport.review_status === "reviewed" ? "Human reviewed" : "Unreviewed"}
          </span>
        </p>
      </div>

      <dl>
        {Object.entries(passport.attributes).map(([field, attribute]) => (
          <div key={field} className="passport-attribute">
            <dt>
              {FIELD_LABELS[field] ?? field}{" "}
              <span className={`badge provenance-${attribute.provenance}`}>
                {PROVENANCE_LABELS[attribute.provenance] ?? attribute.provenance}
              </span>
            </dt>
            <dd>
              {attribute.value === null || attribute.value === undefined
                ? "Unknown"
                : String(attribute.value)}
            </dd>
          </div>
        ))}
      </dl>

      {passport.possible_applications.length > 0 && (
        <>
          <h3>Possible applications</h3>
          <ul className="chip-list">
            {passport.possible_applications.map((entry) => (
              <li key={entry} className="chip">
                {entry}
              </li>
            ))}
          </ul>
        </>
      )}
      {passport.suitable_industries.length > 0 && (
        <>
          <h3>Suitable industries</h3>
          <ul className="chip-list">
            {passport.suitable_industries.map((entry) => (
              <li key={entry} className="chip">
                {entry}
              </li>
            ))}
          </ul>
        </>
      )}
      {passport.candidate_pathways.length > 0 && (
        <>
          <h3>Candidate circular pathways</h3>
          <ul className="chip-list">
            {passport.candidate_pathways.map((entry) => (
              <li key={entry} className="chip">
                {entry}
              </li>
            ))}
          </ul>
        </>
      )}
      {passport.notes && <p className="muted">{passport.notes}</p>}

      {!editing ? (
        <div className="form-actions">
          <button type="button" className="btn" onClick={beginEdit}>
            Edit (new version)
          </button>
          {passport.review_status === "reviewed" ? (
            <button
              type="button"
              className="btn"
              onClick={() => handleReview("unreviewed")}
              disabled={busy}
            >
              Mark unreviewed
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => handleReview("reviewed")}
              disabled={busy}
            >
              Mark reviewed
            </button>
          )}
        </div>
      ) : (
        <div className="form">
          <label className="field">
            <span>Possible applications (comma-separated)</span>
            <input
              value={applications}
              onChange={(e) => setApplications(e.target.value)}
              placeholder="e.g. Cable manufacturing, Conductive fillers"
            />
          </label>
          <label className="field">
            <span>Suitable industries (comma-separated)</span>
            <input
              value={industries}
              onChange={(e) => setIndustries(e.target.value)}
              placeholder="e.g. Electrical equipment, Construction"
            />
          </label>
          <label className="field">
            <span>Candidate pathways (comma-separated)</span>
            <input
              value={pathways}
              onChange={(e) => setPathways(e.target.value)}
              placeholder="reuse, recycle, upcycle, remanufacture"
            />
          </label>
          <label className="field">
            <span>Notes</span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </label>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={handleSave} disabled={busy}>
              {busy ? "Saving..." : "Save as new version"}
            </button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          <p className="muted">
            Saving creates version {passport.version + 1}; the current version is
            superseded and the new version starts unreviewed.
          </p>
        </div>
      )}
    </section>
  );
}
