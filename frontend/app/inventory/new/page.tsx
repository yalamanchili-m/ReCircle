"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import type { EnrichmentResponse, Listing, ListingInput, MaterialSuggestionResponse } from "@/lib/types";
import { MATERIAL_CATEGORIES, UNITS } from "@/lib/types";

const EMPTY_FORM: ListingInput = {
  title: "",
  description: "",
  category: "metals",
  material_name: "",
  composition: "",
  grade: "",
  condition: "",
  contamination_notes: "",
  quantity: "",
  unit: "kg",
  price_per_unit: "",
  city: "",
  region: "",
  available_from: "",
};

export default function NewListingPage() {
  const router = useRouter();
  const { ready } = useRequireAuth(["generator", "admin"]);
  const [form, setForm] = useState<ListingInput>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestionNote, setSuggestionNote] = useState<string | null>(null);

  function update<K extends keyof ListingInput>(field: K, value: ListingInput[K]) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSuggest() {
    if (!form.description.trim()) {
      setSuggestionNote("Write a description first, then ask for suggestions.");
      return;
    }
    setSuggesting(true);
    setSuggestionNote(null);
    try {
      const response = await apiFetch<EnrichmentResponse>("/ai/enrich-description", {
        method: "POST",
        body: JSON.stringify({ description: form.description }),
      });
      const s = response.suggestions;
      setForm((prev) => ({
        ...prev,
        category: s.category ?? prev.category,
        material_name: prev.material_name || s.material_name || "",
        quantity: prev.quantity || (s.quantity != null ? String(s.quantity) : ""),
        unit: s.unit ?? prev.unit,
      }));
      const missing = s.missing_information.length
        ? ` Missing: ${s.missing_information.join(", ")}.`
        : "";
      setSuggestionNote(
        `${response.available ? "AI" : "Offline rule-based"} suggestions applied${
          s.category || s.quantity ? "" : " (nothing found)"
        }. All suggestions need your review.${missing}`,
      );
    } catch (err) {
      setSuggestionNote(
        err instanceof ApiError ? err.message : "Suggestions unavailable — you can continue manually.",
      );
    } finally {
      setSuggesting(false);
    }
  }

  async function handleMaterialSuggest() {
    if (!form.description.trim()) {
      setSuggestionNote("Write a description first, then ask for suggestions.");
      return;
    }
    setSuggesting(true);
    setSuggestionNote(null);
    try {
      const result = await apiFetch<MaterialSuggestionResponse>("/ai/material-suggestions", {
        method: "POST",
        body: JSON.stringify({ description: form.description }),
      });
      const s = result.suggestions;
      const type = s.material_type.value as { type_id: string; label: string } | null;
      setForm((prev) => ({
        ...prev,
        category: s.category.value ?? prev.category,
        material_name: prev.material_name || (type ? type.label : ""),
      }));
      setSuggestionNote(
        `Material intelligence (${result.method}, ${result.model_version}): ` +
          `${type ? type.label : "no confident match"} — review and edit before accepting. ` +
          `${result.missing_information.length ? "Missing: " + result.missing_information.join(", ") + "." : ""}`,
      );
    } catch (err) {
      setSuggestionNote(
        err instanceof ApiError ? err.message : "Suggestions unavailable — you can continue manually.",
      );
    } finally {
      setSuggesting(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
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
      const listing = await apiFetch<Listing>("/listings", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      router.push(`/inventory/${listing.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create listing");
    } finally {
      setSubmitting(false);
    }
  }

  if (!ready) {
    return (
      <main className="container">
        <div className="muted">Checking access...</div>
      </main>
    );
  }

  return (
    <main className="container narrow">
      <header>
        <h1>New listing</h1>
        <p>Listings are saved as drafts; activate them to publish to the marketplace.</p>
      </header>

      {error && <div className="alert error">{error}</div>}

      <form onSubmit={handleSubmit} className="card form">
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
          <span>Description *</span>
          <textarea
            value={form.description}
            onChange={(e) => update("description", e.target.value)}
            required
            rows={4}
          />
        </label>

          <div className="suggest-row">
            <button type="button" className="btn" onClick={handleSuggest} disabled={suggesting}>
              {suggesting ? "Analyzing..." : "Suggest fields (optional AI)"}
            </button>
            <button
              type="button"
              className="btn"
              onClick={handleMaterialSuggest}
              disabled={suggesting}
            >
              Suggest material type (taxonomy)
            </button>
            {suggestionNote && <span className="muted suggest-note">{suggestionNote}</span>}
          </div>

        <div className="form-row">
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
          <label className="field">
            <span>Material name</span>
            <input
              value={form.material_name}
              onChange={(e) => update("material_name", e.target.value)}
              maxLength={120}
            />
          </label>
        </div>

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
              maxLength={100}
            />
          </label>
          <label className="field">
            <span>Region</span>
            <input
              value={form.region}
              onChange={(e) => update("region", e.target.value)}
              maxLength={100}
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
          <span>Composition</span>
          <textarea
            value={form.composition}
            onChange={(e) => update("composition", e.target.value)}
            rows={2}
          />
        </label>

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
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Saving..." : "Create draft listing"}
          </button>
          <button type="button" className="btn" onClick={() => router.push("/inventory")}>
            Cancel
          </button>
        </div>
      </form>
    </main>
  );
}
