"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiError, login } from "@/lib/auth";

const DEMO_ACCOUNTS = [
  { label: "Generator", email: "generator@recircle.local" },
  { label: "Buyer", email: "buyer@recircle.local" },
  { label: "Admin", email: "admin@recircle.local" },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed. Is the backend running?");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="container narrow">
      <header>
        <h1>Log in</h1>
        <p>Demo sign-in for ReCircle. Passwords are local demo credentials only.</p>
      </header>

      {error && <div className="alert error">{error}</div>}

      <form onSubmit={handleSubmit} className="card form">
        <label className="field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="username"
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>

      <div className="card demo-accounts">
        <h2>Demo accounts</h2>
        <p className="muted">
          Click to fill the form. All demo passwords are <code>ReCircleDemo123!</code>
        </p>
        <div className="demo-buttons">
          {DEMO_ACCOUNTS.map((account) => (
            <button
              key={account.email}
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setEmail(account.email);
                setPassword("ReCircleDemo123!");
              }}
            >
              {account.label}
            </button>
          ))}
        </div>
      </div>
    </main>
  );
}
