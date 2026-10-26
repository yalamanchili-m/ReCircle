"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import { DashboardSummary } from "@/lib/types";

export default function DashboardPage() {
  const { ready } = useRequireAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ready) return;
    apiFetch<DashboardSummary>("/dashboard/summary")
      .then(setSummary)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load dashboard"),
      )
      .finally(() => setLoading(false));
  }, [ready]);

  return (
    <main className="container">
      <header>
        <h1>Dashboard</h1>
        <p>Live summary derived from PostgreSQL.</p>
      </header>

      {error && <div className="alert error">{error}</div>}
      {loading && <div className="muted">Loading summary...</div>}

      {summary && (
        <>
          <div className="stats-grid">
            <div className="card stat">
              <span className="stat-number">{summary.active_listings}</span>
              <span className="stat-label">Active listings</span>
            </div>
            <div className="card stat">
              <span className="stat-number">{summary.requirements_count}</span>
              <span className="stat-label">Active requirements</span>
            </div>
            <div className="card stat">
              <span className="stat-number">{summary.matches_count}</span>
              <span className="stat-label">Stored matches</span>
            </div>
          </div>

          <section className="card">
            <h2>Available quantity by unit</h2>
            {summary.quantity_by_unit.length === 0 ? (
              <p className="muted">No active listings with quantity.</p>
            ) : (
              <div className="breakdown">
                {summary.quantity_by_unit.map((row) => (
                  <span key={row.unit} className="breakdown-chip">
                    <strong>{row.total.toLocaleString()}</strong> {row.unit} &middot;{" "}
                    {row.listing_count} listing{row.listing_count === 1 ? "" : "s"}
                  </span>
                ))}
              </div>
            )}
            <p className="muted small-note">
              Quantities are grouped per unit and never summed across incompatible units.
            </p>
          </section>

          <section className="card">
            <h2>Recent inventory activity</h2>
            {summary.recent_listings.length === 0 ? (
              <p className="muted">No listings yet.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Quantity</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.recent_listings.map((listing) => (
                    <tr key={listing.id}>
                      <td>
                        <Link href={`/inventory/${listing.id}`} className="table-link">
                          {listing.title}
                        </Link>
                      </td>
                      <td>
                        <span className={`badge status-${listing.status}`}>{listing.status}</span>
                      </td>
                      <td>
                        {listing.quantity} {listing.unit}
                      </td>
                      <td>{new Date(listing.updated_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <div className="dash-links">
            <Link href="/inventory" className="btn">
              Manage inventory
            </Link>
            <Link href="/marketplace" className="btn">
              Browse marketplace
            </Link>
            <Link href="/matches" className="btn">
              Generate matches
            </Link>
          </div>
        </>
      )}
    </main>
  );
}