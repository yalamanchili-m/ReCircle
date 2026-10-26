"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type { Listing, ListingInput } from "@/lib/types";
import { MATERIAL_CATEGORIES, UNITS } from "@/lib/types";
import PassportPanel from "@/components/PassportPanel";

function toForm(listing: Listing): ListingInput {
  return {
    title: listing.title,
    description: listing.description,
    category: listing.category,
    material_name: listing.material_name ?? "",
    composition: listing.composition ?? "",
    grade: listing.grade ?? "",
    condition: listing.condition ?? "",
    contamination_notes: listing.contamination_notes ?? "",
    quantity: listing.quantity,
    unit: listing.unit,
    price_per_unit: listing.price_per_unit ?? "",
    city: listing.city,
    region: listing.region ?? "",
    available_from: listing.available_from ?? "",
  };
}

export default function ListingDetailPage() {
  const params = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const [listing, setListing] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<ListingInput | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const result = await apiFetch<Listing>(`/listings/${params.id}`);
      setListing(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load listing");
    }
  }, [params.id]);

  useEffect(() => {
    if (!ready) return;
    load();
  }, [load, ready]);

  function update<K extends keyof ListingInput>(field: K, value: ListingInput[K]) {
    setForm((prev) => (prev ? { ...prev, [field]: value } : prev));
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setActionError(null);
    try {
      const payload = {
        ...form,
        material_name: form.material_name || null,
        composition: form.composition || null,
        grade: form.grade || null,
        condition: form.condition || null,
        contamination_notes: form.contamination_notes || null,
        region: form.region || null,
        price_per_unit: form.price_per_unit || null,
        available_from: form.available_from || null,
      };
      const updated = await apiFetch<Listing>(`/listings/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setListing(updated);
      setEditing(false);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not save changes");
    } finally {
      setSaving(false);
    }
  }

  async function handleAction(action: "activate" | "archive") {
    setActionError(null);
    try {
      const updated = await apiFetch<Listing>(`/listings/${params.id}/${action}`, {
        method: "POST",
      });
      setListing(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed");
    }
  }

  if (error) {
    return (
      <main className="container">
        <div className="alert error">{error}</div>
        <Link href="/inventory" className="btn">
          Back to inventory
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

  const archived = listing.status === "archived";

  return (
    <main className="container">
      <header className="page-header">
        <div>
          <h1>{listing.title}</h1>
          <p>
            <span className={`badge status-${listing.status}`}>{listing.status}</span>
            {"  "}
            <span className="muted">
              {listing.category} &middot; {listing.quantity} {listing.unit} &middot;{" "}
              {listing.city}
              {listing.region ? `, ${listing.region}` : ""}
            </span>
          </p>
        </div>
        <div className="actions">
          {!archived && !editing && listing.status === "draft" && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => handleAction("activate")}
            >
              Activate
            </button>
          )}
          {!archived && !editing && (
            <button type="button" className="btn" onClick={() => handleAction("archive")}>
              Archive
            </button>
          )}
          {!archived && (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setForm(toForm(listing));
                setEditing((prev) => !prev);
              }}
            >
              {editing ? "Close editor" : "Edit"}
            </button>
          )}
        </div>
      </header>

      {actionError && <div className="alert error">{actionError}</div>}

      {editing && form && (
        <form onSubmit={handleSave} className="card form">
          <div className="form-row">
            <label className="field">
              <span>Title *</span>
              <input
                value={form.title}
                onChange={(e) => update("title", e.target.value)}
                required
                maxLength={180}
              />
            </label>
            <label className="field">
              <span>Category *</span>
              <select
                value={form.category}
                onChange={(e) => update("category", e.target.value)}
              >
                {MATERIAL_CATEGORIES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="field">
            <span>Description *</span>
            <textarea
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              required
              rows={3}
            />
          </label>

          <div className="form-row">
            <label className="field">
              <span>Quantity *</span>
              <input
                type="number"
                step="0.001"
                min="0.001"
                value={form.quantity}
                onChange={(e) => update("quantity", e.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Unit *</span>
              <select value={form.unit} onChange={(e) => update("unit", e.target.value)}>
                {UNITS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Price per unit</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.price_per_unit}
                onChange={(e) => update("price_per_unit", e.target.value)}
              />
            </label>
          </div>

          <div className="form-row">
            <label className="field">
              <span>City *</span>
              <input
                value={form.city}
                onChange={(e) => update("city", e.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Region</span>
              <input
                value={form.region}
                onChange={(e) => update("region", e.target.value)}
              />
            </label>
          </div>

          <div className="form-row">
            <label className="field">
              <span>Grade</span>
              <input value={form.grade} onChange={(e) => update("grade", e.target.value)} />
            </label>
            <label className="field">
              <span>Condition</span>
              <input
                value={form.condition}
                onChange={(e) => update("condition", e.target.value)}
              />
            </label>
          </div>

          <label className="field">
            <span>Contamination notes</span>
            <textarea
              value={form.contamination_notes}
              onChange={(e) => update("contamination_notes", e.target.value)}
              rows={2}
            />
          </label>

          <label className="field">
            <span>Available from</span>
            <input
              type="date"
              value={form.available_from}
              onChange={(e) => update("available_from", e.target.value)}
            />
          </label>

          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving..." : "Save changes"}
            </button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {!editing && (
        <>
          <div className="detail-grid">
            <section className="card">
              <h2>Material</h2>
              <dl>
                <dt>Description</dt>
                <dd>{listing.description}</dd>
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
                    : "Not specified"}
                </dd>
                <dt>Available from</dt>
                <dd>{listing.available_from ?? "Immediately"}</dd>
                <dt>Location</dt>
                <dd>
                  {listing.city}
                  {listing.region ? `, ${listing.region}` : ""}, {listing.country}
                </dd>
                <dt>Last updated</dt>
                <dd>{new Date(listing.updated_at).toLocaleString()}</dd>
              </dl>
            </section>
          </div>
          <PassportPanel listingId={listing.id} />
        </>
      )}

      <p>
        <Link href="/inventory" className="btn">
          Back to inventory
        </Link>
      </p>
    </main>
  );
}
