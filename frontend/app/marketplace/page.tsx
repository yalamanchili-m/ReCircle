"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/useRequireAuth";
import { MarketplaceListing, MATERIAL_CATEGORIES, UNITS } from "@/lib/types";

export default function MarketplacePage() {
  const { ready } = useRequireAuth();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [city, setCity] = useState("");
  const [unit, setUnit] = useState("");
  const [minQuantity, setMinQuantity] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ items: MarketplaceListing[]; total: number; page: number; page_size: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "10" });
      if (q) params.set("q", q);
      if (category) params.set("category", category);
      if (city) params.set("city", city);
      if (unit) params.set("unit", unit);
      if (minQuantity) params.set("min_quantity", minQuantity);
      if (maxPrice) params.set("max_price", maxPrice);
      const result = await apiFetch<{ items: MarketplaceListing[]; total: number; page: number; page_size: number }>(
        `/marketplace/listings?${params.toString()}`,
      );
      setData(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load marketplace");
    } finally {
      setLoading(false);
    }
  }, [q, category, city, unit, minQuantity, maxPrice, page]);

  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(load, q || minQuantity || maxPrice ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, q, minQuantity, maxPrice, ready]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <main className="container">
      <header>
        <h1>Marketplace</h1>
        <p>Active material listings from all organizations.</p>
      </header>

      <div className="filters card">
        <input
          type="search"
          placeholder="Search materials..."
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
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
        <input
          type="search"
          placeholder="City"
          value={city}
          onChange={(e) => {
            setCity(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={unit}
          onChange={(e) => {
            setUnit(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Any unit</option>
          {UNITS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <input
          type="number"
          placeholder="Min qty"
          min="0"
          value={minQuantity}
          onChange={(e) => {
            setMinQuantity(e.target.value);
            setPage(1);
          }}
        />
        <input
          type="number"
          placeholder="Max price"
          min="0"
          value={maxPrice}
          onChange={(e) => {
            setMaxPrice(e.target.value);
            setPage(1);
          }}
        />
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <div className="muted">Searching marketplace...</div>}

      {data && !loading && data.items.length === 0 && (
        <div className="card empty">
          <p>No active listings match your search.</p>
          <p className="muted">Try clearing filters or searching for a broader term.</p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          <p className="muted result-count">
            {data.total} active listing{data.total === 1 ? "" : "s"}
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Material</th>
                <th>Organization</th>
                <th>Category</th>
                <th>Quantity</th>
                <th>Price</th>
                <th>Location</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((listing) => (
                <tr key={listing.id}>
                  <td>
                    <Link href={`/marketplace/${listing.id}`} className="table-link">
                      {listing.title}
                    </Link>
                  </td>
                  <td>{listing.organization_name}</td>
                  <td>{listing.category}</td>
                  <td>
                    {listing.quantity} {listing.unit}
                  </td>
                  <td>
                    {listing.price_per_unit
                      ? `${listing.price_per_unit} ${listing.currency}/${listing.unit}`
                      : "—"}
                  </td>
                  <td>
                    {listing.city}
                    {listing.region ? `, ${listing.region}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <span className="muted">
              Page {data.page} of {totalPages}
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