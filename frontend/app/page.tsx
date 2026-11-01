"use client";

import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type { HealthDbResponse, HealthResponse } from "@/lib/types";

type Status = "pending" | "ok" | "error";

interface Check {
  label: string;
  status: Status;
  detail: string;
}

export default function Home() {
  const [checks, setChecks] = useState<Check[]>([
    { label: "Backend API", status: "pending", detail: "Checking..." },
    { label: "PostgreSQL", status: "pending", detail: "Checking..." },
  ]);

  useEffect(() => {
    async function run() {
      const results: Check[] = [];

      try {
        const health = await apiFetch<HealthResponse>("/health");
        results.push({
          label: "Backend API",
          status: "ok",
          detail: `${health.app} (${health.env}) responded`,
        });
      } catch (error) {
        results.push({
          label: "Backend API",
          status: "error",
          detail: error instanceof ApiError ? error.message : "Unreachable",
        });
      }

      try {
        const healthDb = await apiFetch<HealthDbResponse>("/health/db");
        results.push({
          label: "PostgreSQL",
          status: healthDb.database === "connected" ? "ok" : "error",
          detail: healthDb.database === "connected" ? "Database connection verified" : "Database unavailable",
        });
      } catch (error) {
        results.push({
          label: "PostgreSQL",
          status: "error",
          detail: error instanceof ApiError ? error.message : "Unreachable",
        });
      }

      setChecks(results);
    }

    run();
  }, []);

  return (
    <main className="container">
      <header>
        <h1>ReCircle</h1>
        <p>Milestone 1 &mdash; Foundation status</p>
      </header>

      {checks.map((check) => (
        <div className="card" key={check.label}>
          <div>
            <h2>{check.label}</h2>
            <div className="detail">{check.detail}</div>
          </div>
          <span className={`badge ${check.status}`}>
            {check.status === "pending" ? "checking" : check.status === "ok" ? "connected" : "failed"}
          </span>
        </div>
      ))}

      <footer>
        Backend must be running on port 8000; PostgreSQL on 5432. See README for setup.
      </footer>
    </main>
  );
}
