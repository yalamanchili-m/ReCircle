"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import { MarketplaceListing, MaterialPassport } from "@/lib/types";

const PROVENANCE_LABELS: Record<string, string> = {
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

export default function MarketplaceListingDetailPage() {
  const params = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const [listing, setListing] = useState<MarketplaceListing | null>(null);
  const [passport, setPassport] = useState<MaterialPassport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const result = await apiFetch<MarketplaceListing>(`/marketplace/listings/${params.id}`);
      setListing(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load listing");
    }
  }, [params.id]);

  useEffect(() => {
    if (!ready) return;
    load();
  }, [load, ready]);

  useEffect(() => {
    if (!ready || !listing) return;
    apiFetch<MaterialPassport>(`/marketplace/listings/${params.id}/passport`)
      .then(setPassport)
      .catch(() => setPassport(null)); // passport is optional for a listing
  }, [ready, listing, params.id]);

  if (error) {
    return (
      <main className="container">
        <div className="alert error">{error}</div>
        <Link href="/marketplace" className="btn">
          Back to marketplace
        </Link>
      </main>
    );
  }

  if (!listing) {
    return (
      <main className="container">
        <p className="muted">Loading listing...</p>
      </main>
    );
  }

  return (
    <main className="container">
      <header>
        <h1>{listing.title}</h1>
        <p>
          <span className="muted">
            Listed by <strong>{listing.organization_name}</strong> &middot;{" "}
            {listing.city}
            {listing.region ? `, ${listing.region}` : ""}
          </span>
        </p>
      </header>

      <div className="detail-grid">
        <section className="card">
          <h2>Material</h2>
          <dl>
            <dt>Description</dt>
            <dd>{listing.description}</dd>
            <dt>Category</dt>
            <dd>{listing.category}</dd>
            <dt>Material name</dt>
            <dd>{listing.material_name ?? "—"}</dd>
            <dt>Composition</dt>
            <dd>{listing.composition ?? "—"}</dd>
            <dt>Grade</dt>
            <dd>{listing.grade ?? "—"}</dd>
            <dt>Condition</dt>
            <dd>{listing.condition ?? "—"}</dd>
            <dt>Contamination notes</dt>
            <dd>{listing.contamination_notes ?? "None recorded"}</dd>
          </dl>
        </section>
        <section className="card">
          <h2>Availability</h2>
          <dl>
            <dt>Quantity</dt>
            <dd>
              {listing.quantity} {listing.unit}
            </dd>
            <dt>Price</dt>
            <dd>
              {listing.price_per_unit
                ? `${listing.price_per_unit} ${listing.currency} per ${listing.unit}`
                : "Not specified — contact the organization"}
            </dd>
            <dt>Available from</dt>
            <dd>{listing.available_from ?? "Immediately"}</dd>
            <dt>Last updated</dt>
            <dd>{new Date(listing.updated_at).toLocaleString()}</dd>
          </dl>
        </section>
      </div>

      {passport && (
        <section className="card">
          <h2>Material Passport</h2>
          <p className="muted">
            Version {passport.version} &middot;{" "}
            {passport.review_status === "reviewed"
              ? "Human reviewed"
              : "Unreviewed — attribute values are not independently verified"}
          </p>
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
              <p>{passport.possible_applications.join(", ")}</p>
            </>
          )}
          {passport.suitable_industries.length > 0 && (
            <>
              <h3>Suitable industries</h3>
              <p>{passport.suitable_industries.join(", ")}</p>
            </>
          )}
        </section>
      )}

      <p>
        <Link href="/marketplace" className="btn">
          Back to marketplace
        </Link>
      </p>
    </main>
  );
}