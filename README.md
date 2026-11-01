# ReCircle

Industrial circular-economy application: waste-material inventory,
materials marketplace, and explainable material matching.

Stack: Next.js + TypeScript frontend, Python FastAPI backend, PostgreSQL,
optional local Ollama for AI-assisted description enrichment.

## Milestone 6 status (Dashboard and optional AI)

- [x] `GET /api/dashboard/summary` — backend aggregation: active listings,
      available quantity grouped per unit (kg and litres are never summed
      together), active requirements, stored matches, recent inventory activity
- [x] `POST /api/ai/enrich-description` — optional Ollama adapter with strict
      output validation; invalid/invented model values are dropped
- [x] Deterministic rule-based fallback when Ollama is offline, slow, or
      returns malformed output; response always marked `needs_review`
- [x] Inventory form has an optional "Suggest fields" button that pre-fills
      category/material name/quantity/unit for user review
- [x] Frontend dashboard with summary cards, per-unit totals, and recent
      activity; login lands on the dashboard
- [x] 11 new tests: dashboard-vs-database consistency, unit isolation, Ollama
      offline/timeout/malformed paths, model validation, auth

Gate: dashboard numbers correspond to the database, and AI failure does not
block inventory, marketplace, or matching.

## Demo walkthrough (end-to-end checklist)

1. Start backend and frontend (commands above), open http://localhost:3000.
2. Log in as **generator** (quick-fill buttons on the login page).
3. Dashboard shows live counts for your organization.
4. Inventory → **New listing** → fill the form (or paste a description and use
   **Suggest fields**), create, then **Activate**.
5. Log out, log in as **buyer**.
6. Marketplace → find the new listing; filters and search hit PostgreSQL.
7. Requirements → create a requirement (or use seeded ones).
8. Matches → pick the requirement, **Generate matches**; inspect the score,
   per-criterion breakdown, explanation, and warnings; optionally save a
   snapshot.
9. Dashboard → verify counts changed.
10. Log back in as generator, archive the listing, and confirm it disappears
    from default marketplace results.

## Ollama (optional)

- Install Ollama locally and pull any model, then set `OLLAMA_MODEL` in
  `backend/.env` (default `llama3.2`, base URL `http://localhost:11434`).
- Without Ollama the app is fully functional; enrichment returns a
  deterministic offline extraction marked `available: false`.
- AI output is advisory only and is never stored without user confirmation.

## Milestone 5 status (Matching)

- [x] Requirements API: `GET/POST /api/requirements`,
      `GET/PATCH /api/requirements/{id}` with role and ownership checks
- [x] `POST /api/requirements/{id}/matches` — deterministic scoring of active
      listings against a requirement; `?persist=true` stores snapshots
- [x] `GET /api/requirements/{id}/matches` — retrieve stored snapshots
- [x] Scoring weights: category 40 (mismatch rejects), quantity 25
      (proportional when short; incompatible units score 0 with warning),
      quality 20 (unknown grade = partial + "unverified" warning), location 10
      (city > region > partial > unknown), price 5 (unpriced = 0 + warning)
- [x] Missing criteria (grade/location/budget) are excluded and remaining
      weights normalized to 0-100; missing data is never a positive match
- [x] Stable tie-breaking; same input + same data = same results
- [x] Frontend: requirements page (list + create form) and matches page with
      score, per-criterion breakdown chips, explanations, and warnings
- [x] 18 matching/requirements tests covering exact, partial, insufficient
      quantity, unknown quality, unit mismatch, budget edge cases,
      determinism, and persistence

Gate: a buyer can generate ranked candidates from real database records and
understand why each match appears.

## Milestone 4 status (Marketplace)

- [x] `GET /api/marketplace/listings` — server-side search (ILIKE on
      title/description), filters (category, city, region, min quantity +
      unit, max price), and pagination; only `active` listings are returned
- [x] `GET /api/marketplace/listings/{id}` — public detail showing material
      info and the organization name only (no private account details)
- [x] Quantity/price sanity: min quantity filters only comparable units;
      unpriced listings are excluded from max-price filtering
- [x] Frontend: marketplace page with search box and all filters, results
      table with organization names, public detail page, nav link
- [x] 11 marketplace tests (visibility, filters, pagination, privacy, auth)

Gate: newly activated listings appear in search, and archived listings do not.

## Milestone 3 status (Inventory)

- [x] `GET/POST /api/listings`, `GET/PATCH /api/listings/{id}`,
      `POST /api/listings/{id}/activate|archive`
- [x] Validation: quantity > 0, supported units and categories, required fields
- [x] Status transitions: draft → active → archived (409 on invalid moves)
- [x] Ownership enforced server-side: only the owner organization (or admin)
      may view, edit, activate, or archive a listing
- [x] Search (ILIKE), status/category filters, pagination
- [x] Frontend: login page with demo accounts, nav bar, inventory table with
      filters and pagination, create form, detail/edit page with
      activate/archive actions
- [x] 21 automated inventory tests (validation, ownership, transitions,
      filters, pagination)

Gate: a listing created in the UI is persisted and survives refresh and
backend restart.

## Milestone 2 status (Seed data and demo authentication)

- [x] Full initial schema migrated (organizations, users, waste_listings,
      material_requirements, matches, offers, transactions, recovery_records,
      notifications, audit_logs)
- [x] Idempotent seed: 3 demo organizations/users, 5 synthetic listings,
      3 buyer requirements (`python -m app.db.seed`)
- [x] `POST /api/auth/login` issues short-lived JWT access tokens
- [x] `GET /api/auth/me`, `GET/PATCH /api/organizations/me` (authenticated)
- [x] Passwords stored as Argon2 hashes only

Gate: generator and buyer demo accounts log in and receive role-appropriate
data.

### Demo credentials (local demonstration ONLY)

| Role      | Email                      | Password         |
|-----------|----------------------------|------------------|
| Generator | generator@recircle.local   | ReCircleDemo123! |
| Buyer     | buyer@recircle.local       | ReCircleDemo123! |
| Admin     | admin@recircle.local       | ReCircleDemo123! |

## Milestone 1 status (Foundation)

- [x] FastAPI backend scaffolded (`code/backend`)
- [x] Next.js frontend scaffolded (`code/frontend`)
- [x] PostgreSQL connected (`recircle` database, `recircle_app` role)
- [x] Alembic migrations wired (`backend/migrations`)
- [x] Health endpoints: `GET /api/health` and `GET /api/health/db`
- [x] Frontend displays backend + database status from live API calls

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL (local server running on port 5432)
- Docker is optional (not required; PostgreSQL runs locally)

## Database setup (one time)

```powershell
psql -U postgres -h localhost -c "CREATE USER recircle_app WITH PASSWORD 'local_dev_password';"
psql -U postgres -h localhost -c "CREATE DATABASE recircle OWNER recircle_app;"
```

## Backend

```powershell
cd code\backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # adjust if your credentials differ
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m app.db.seed
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

- API docs: http://localhost:8000/api/docs
- Health: http://localhost:8000/api/health
- DB health: http://localhost:8000/api/health/db

## Frontend

```powershell
cd code\frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open http://localhost:3000 — the page checks `/api/health` and
`/api/health/db` through the backend and shows live connection status.

## Tests

```powershell
cd code\backend
.venv\Scripts\python -m pytest tests -q
```

To prove the Alembic chain builds the full schema from an empty database
(without touching the `recircle` dev database), run the fresh-database gate.
It creates a disposable `recircle_test` database, applies all migrations,
runs the whole suite against it, then drops it:

```powershell
powershell -ExecutionPolicy Bypass -File D:\ReCircle\scripts\run_tests_fresh_db.ps1
```

## Security notes

- Never commit `.env` / `.env.local`; both are gitignored.
- Demo credentials used in later milestones are for local demonstration only.

## Known limitations

- Inventory/marketplace/matching workflows arrive in Milestones 3–5.
- Demo accounts are not production identity; registration and password
  reset are deferred.
- All seed records are clearly marked synthetic data; real datasets are
  deferred until supplied.
