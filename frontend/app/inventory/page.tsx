"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import { ListingPage, MATERIAL_CATEGORIES } from "@/lib/types";

const STATUS_OPTIONS = ["", "draft", "active", "matched", "archived"];

export default function InventoryPage() {
  const { ready, user } = useRequireAuth();
  const role = user?.role ?? null;
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ListingPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "10" });
      if (q) params.set("q", q);
      if (status) params.set("status", status);
      if (category) params.set("category", category);
      const result = await apiFetch<ListingPage>(`/listings?${params.toString()}`);
      setData(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load inventory");
    } finally {
      setLoading(false);
    }
  }, [q, status, category, page]);

  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(load, q ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, q, ready]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <main className="container">
      <header className="page-header">
        <div>
          <h1>Inventory</h1>
          <p>Material listings owned by your organization.</p>
        </div>
        {role !== "buyer" && (
          <Link href="/inventory/new" className="btn btn-primary">
            New listing
          </Link>
        )}
      </header>

      <div className="filters card">
        <input
          type="search"
          placeholder="Search title or description..."
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option === "" ? "All statuses" : option}
            </option>
          ))}
        </select>
        <select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All categories</option>
          {MATERIAL_CATEGORIES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <div className="muted">Loading listings...</div>}

      {data && !loading && data.items.length === 0 && (
        <div className="card empty">
          <p>No listings match your filters.</p>
          <p className="muted">
            Create a listing to see it here — it persists in PostgreSQL.
          </p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Category</th>
                <th>Quantity</th>
                <th>Location</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((listing) => (
                <tr key={listing.id}>
                  <td>
                    <Link href={`/inventory/${listing.id}`} className="table-link">
                      {listing.title}
                    </Link>
                  </td>
                  <td>{listing.category}</td>
                  <td>
                    {listing.quantity} {listing.unit}
                  </td>
                  <td>{listing.city}</td>
                  <td>
                    <span className={`badge status-${listing.status}`}>{listing.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <span className="muted">
              Page {data.page} of {totalPages} &middot; {data.total} listing
              {data.total === 1 ? "" : "s"}
            </span>
            <button
              type="button"
              className="btn"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </main>
  );
}
