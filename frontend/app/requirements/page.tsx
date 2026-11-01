"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import { Requirement, MATERIAL_CATEGORIES, UNITS } from "@/lib/types";

const EMPTY_FORM = {
  title: "",
  category: "metals",
  description: "",
  min_quantity: "",
  unit: "kg",
  required_grade: "",
  max_price_per_unit: "",
  preferred_city: "",
  preferred_region: "",
};

export default function RequirementsPage() {
  const { ready, user } = useRequireAuth(["buyer", "admin"]);
  const role = user?.role ?? null;
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiFetch<Requirement[]>("/requirements?status=active");
      setRequirements(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load requirements");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    load();
  }, [load, ready]);

  function update(field: keyof typeof EMPTY_FORM, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const payload = {
        title: form.title,
        category: form.category,
        description: form.description || null,
        min_quantity: form.min_quantity,
        unit: form.unit,
        required_grade: form.required_grade || null,
        max_price_per_unit: form.max_price_per_unit || null,
        preferred_city: form.preferred_city || null,
        preferred_region: form.preferred_region || null,
      };
      await apiFetch<Requirement>("/requirements", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create requirement");
    }
  }

  const canCreate = role === "buyer" || role === "admin";

  return (
    <main className="container">
      <header className="page-header">
        <div>
          <h1>Material requirements</h1>
          <p>What your organization is looking for. Used to generate matches.</p>
        </div>
        {canCreate && (
          <button type="button" className="btn btn-primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? "Close form" : "New requirement"}
          </button>
        )}
      </header>

      {!canCreate && role === "generator" && (
        <div className="alert error">
          Generator organizations search the marketplace instead; only buyers and admins
          define requirements.
        </div>
      )}

      {error && <div className="alert error">{error}</div>}
      {loading && <div className="muted">Loading requirements...</div>}

      {showForm && canCreate && (
        <form onSubmit={handleSubmit} className="card form">
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
              <select value={form.category} onChange={(e) => update("category", e.target.value)}>
                {MATERIAL_CATEGORIES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-row">
            <label className="field">
              <span>Minimum quantity *</span>
              <input
                type="number"
                step="0.001"
                min="0.001"
                value={form.min_quantity}
                onChange={(e) => update("min_quantity", e.target.value)}
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
              <span>Max price per unit</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.max_price_per_unit}
                onChange={(e) => update("max_price_per_unit", e.target.value)}
              />
            </label>
          </div>

          <div className="form-row">
            <label className="field">
              <span>Required grade</span>
              <input
                value={form.required_grade}
                onChange={(e) => update("required_grade", e.target.value)}
              />
            </label>
            <label className="field">
              <span>Preferred city</span>
              <input
                value={form.preferred_city}
                onChange={(e) => update("preferred_city", e.target.value)}
              />
            </label>
            <label className="field">
              <span>Preferred region</span>
              <input
                value={form.preferred_region}
                onChange={(e) => update("preferred_region", e.target.value)}
              />
            </label>
          </div>

          <label className="field">
            <span>Notes</span>
            <textarea
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              rows={2}
            />
          </label>

          <div className="form-actions">
            <button type="submit" className="btn btn-primary">
              Create requirement
            </button>
            <button type="button" className="btn" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {requirements.length === 0 && !loading && (
        <div className="card empty">
          <p>No active requirements yet.</p>
          {canCreate && <p className="muted">Create one, then generate matches for it.</p>}
        </div>
      )}

      {requirements.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Category</th>
              <th>Min quantity</th>
              <th>Grade</th>
              <th>Location</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {requirements.map((requirement) => (
              <tr key={requirement.id}>
                <td>{requirement.title}</td>
                <td>{requirement.category}</td>
                <td>
                  {requirement.min_quantity} {requirement.unit}
                </td>
                <td>{requirement.required_grade ?? "Any"}</td>
                <td>
                  {requirement.preferred_city ?? "—"}
                  {requirement.preferred_region ? `, ${requirement.preferred_region}` : ""}
                </td>
                <td>
                  <Link href={`/matches?requirement=${requirement.id}`} className="btn">
                    Matches
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}