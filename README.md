# ReCircle

**ReCircle** is a full-platform industrial circular-economy application. It
enables organizations to publish structured inventories of industrial waste and
secondary materials, discover inputs they can use through a searchable
marketplace, and evaluate supply–demand fit with deterministic, explainable
matching. Beyond the core marketplace workflow, the platform includes a
material intelligence engine, an industrial symbiosis discovery engine, a
circular path optimizer, a carbon impact predictor, an ESG dashboard with
trade-level reporting, a knowledge-graph synchronization layer, a
regulation–news aggregator, a retrieval-augmented sustainability assistant,
staged external-data ingestion, and an ERP integration boundary — all backed by
PostgreSQL as the single source of truth.

## Technical stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 (App Router) + TypeScript + React |
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| Persistence | PostgreSQL + SQLAlchemy 2.0 + Alembic migrations |
| Auth | JWT (HS256, short-lived access tokens), Argon2 password hashing (pwdlib) |
| Graph (optional) | Neo4j 5.28 driver behind an explicit enable flag |
| AI (optional) | Local Ollama; the platform is fully functional without it |
| Testing | pytest — 240 backend tests |

## Architecture

```
Next.js frontend (localhost:3000)
        │  HTTP/JSON, all business data via the API
        ▼
FastAPI backend (localhost:8000, prefix /api)
   routes → services → SQLAlchemy models
        │
        ▼
PostgreSQL (source of truth: organizations, users, listings,
requirements, passports, matches, trades, impact estimates,
analytics runs, regulation items, RAG chunks, ERP records)
        │
        └── optional side services: Neo4j (graph projection), Ollama (AI assists)
```

Design principles the codebase follows:

- **One backend, one relational database.** All validation, authorization,
  business rules, scoring, and aggregation live in FastAPI services; the
  frontend never hardcodes business data.
- **Determinism first.** Every ranking, scoring, clustering, and impact
  calculation is a pure, deterministic function of database state. Identical
  input + identical data always produces identical results. AI is strictly
  advisory and never computes scores.
- **Full provenance.** Persisted estimates, suggestions, and analytical runs
  carry method identifiers, algorithm versions, source references, assumptions,
  and limitations. Values derived from user input, from the system, or from AI
  are tagged distinctly.
- **Honest missing-data semantics.** Unknown values are stored as unknown —
  never zero-filled, never treated as a positive match, and unsupported
  calculations are recorded as unsupported with explicit reasons.
- **Graceful degradation.** Neo4j and Ollama outages never block the core
  inventory → marketplace → matching → ESG workflow.

## Core modules

### Inventory and marketplace
Waste listings with full lifecycle (`draft → active → matched → archived`),
validation (positive quantities, constrained units `kg/tonne/litre/unit`),
server-side ownership enforcement, and immutable transaction history on
archive. The public marketplace serves only active listings with
PostgreSQL-backed text search (`ILIKE`), category/location/quantity/price
filters, and pagination; public detail views expose organization names only,
never private account details.

### Material Passport
Each listing carries a versioned material passport with per-attribute
provenance (`user_provided`, `source_derived`, `ai_inferred`, `unverified`).
Edits create new immutable versions (previous rows become `superseded`), and a
human review flow (`review_status`, reviewer, timestamp) governs publication.
A read-only passport view is exposed for active marketplace listings.

### Material Intelligence Engine
Canonical versioned taxonomy `recircle-taxonomy-v1` (14 material types across
9 categories) with an alias map; original user labels are always preserved.
Suggestions come from a pure-Python TF-IDF + cosine similarity baseline with an
opt-in Sentence-BERT adapter (embedding-only, disabled by default). Accepted
suggestions persist per-field provenance including model version, acceptor,
and timestamp. Unknown materials return `unverified`/null instead of guesses.

### Circular Match Engine (`circular-match-v2`)
Two-stage deterministic ranking:

1. **Weighted baseline** — category 40 (mismatch rejects the candidate
   outright), quantity 25 (kg↔tonne normalized via mass conversion; litre/unit
   vs kg is safely excluded with a warning), quality 20 (unknown grade is
   partial credit with an `unverified` warning), location 10 (city > region >
   unknown), price 5 (over-budget excludes the candidate). Inapplicable
   criteria are dropped and remaining weights renormalized to 0–100.
2. **KNN-style re-rank** — fixed documented weights over a normalized feature
   vector (quantity .35, quality .25, material fit .20, location .15,
   price .05) with a content-based `material_fit` term-cosine score.

Hard constraints (category, status, positive quantity, budget) are enforced
before ranking. Ranked results carry per-criterion score breakdowns, warnings,
and explanations; snapshots persist under a stable requirement/listing pair
with the algorithm version stamped.

### Industrial Symbiosis Discovery
A deterministic in-memory graph mirrors the Neo4j projection (stable node ids,
typed edges with provenance flags) over pure-Python implementations of bounded
BFS shortest paths, degree-normalized PageRank, and deterministic Louvain
community detection. Opportunities combine material fit, availability, graph
proximity, and cluster membership with fixed documented weights, and every
candidate cites its evidence (paths, shared clusters, hub PageRank) plus an
explicit requires-validation marker.

### Circular Path Optimizer
Weighted Sum Model (MCDM) with hard feasibility gates run before ranking
(e.g. chemicals rank only `recycle`), three weight profiles, per-criterion
normalized contributions, missing-criterion renormalization, and a ±25%
sensitivity check. Rejected candidates are explained by the feasibility gate
that excluded them — never by a fabricated score.

### Carbon Impact Predictor
Differential arithmetic: avoided impact = (landfill baseline intensity − route
intensity) × recovered tonnes, computed from a versioned factor catalog with
per-row worst-case uncertainty bands persisted in the assumptions. Estimates
carry full provenance (method, catalog version, source, baseline reference,
limitations); landfill is zero-by-construction and unsupported combinations are
marked `supported=false` with reasons. Ingested external factor sets (e.g.
EPA WARM) automatically take precedence over the curated fallback catalog.

### Explainable AI Engine
A common explanation schema (`explanation-schema-v1`) replays the exact stored
arithmetic for matches, pathways, and impact estimates: per-criterion signed
contributions that sum to the score, caveats with explicit no-causation
language, data-coverage notes, and factor provenance. Predictive-model
surrogates (SHAP/LIME) are documented as not applicable because no predictive
model is deployed; all explanations derive natively from the deterministic
engines.

### Analytics (K-means) and ESG reporting
A deterministic K-means engine (`kmeans-v1`, farthest-first initialization, no
RNG) with silhouette analysis, honest sample-size gating, and persisted,
audited runs. Marketplace metrics reconcile directly to raw tables with mass
normalization (kg and litres are never summed together) and time-series gating
on real multi-month coverage. The ESG dashboard aggregates per recovery record
from the trade workflow (offer → accept → transaction → recovery record →
admin verification), prevents double-counting via a single-current-estimate
constraint, distinguishes `user_reported` / `estimated` / `verified` metric
states, and exports CSV with per-record provenance. Green-credit figures are
indicative visualizations with mandatory disclaimers.

### Knowledge Graph (Neo4j, optional)
A lazy, explicitly-gated Neo4j driver (disabled by default) receives a
deterministic projection (`graph-projection-v1`) of organizations, listings,
requirements, material types, applications, industries, and circular pathways
via idempotent MERGEs on stable ids, with provenance properties on every edge.
Sync runs are recorded — including failures — and a Neo4j outage returns a
safe 503 while PostgreSQL data remains entirely unaffected.

### Regulation–News Aggregator
A curated, keyless source registry (US EPA Newsroom, Federal Register
EPA-waste search, PIB Environment India, EUR-Lex) ingested via a stdlib
RSS 2.0/Atom parser with canonical-URL hash dedup, content-hash change
detection, rate-limit-friendly fetching, and staleness flagging. Summaries
default to publisher excerpts; AI-generated summaries are strictly opt-in and
always labeled. Nothing is presented as legal advice.

### RAG Sustainability Assistant
Retrieval is scoped to the signed-in organization with permission filters
applied **at retrieval time** over an allow-listed corpus: curated trusted
method documents, platform-public regulation/news items (treated as untrusted
external text), and the org's own records plus public marketplace data.
Retrieval is lexical-first (TF-IDF cosine); below-threshold evidence produces
a code-guaranteed abstention — the LLM is never called. The optional Ollama
generation step runs under a strict evidence-only prompt with citation and
prompt-injection defenses, degrading gracefully to extractive answers.

### External data ingestion and ERP integration boundary
Staged, file-based import machinery: sources are a curated registry with
declared adapter status (implemented ones run; planned ones never execute),
raw files are sha256-hashed and staged verbatim separately from normalized
records, missing values are rejected or preserved as explicit nulls (never
zero-filled), and dedup/quarantine/supersede lifecycles keep full history.
Accepted EPA WARM factor sets become the live carbon catalog. The ERP boundary
implements a generic CSV adapter with six entity contracts, admin-only
preview/confirm import (preview stages nothing), cross-row referential
gating, idempotent confirm with content-hash change detection, and authorized
audited CSV exports. Named vendor adapters (SAP S/4HANA OData, Oracle Fusion
Cloud) are registry entries only.

### AI description enrichment (optional)
`POST /api/ai/enrich-description` calls local Ollama behind a timeout with
strict output validation; malformed or invented values are dropped. Offline,
it falls back to deterministic rule-based extraction. Suggestions are always
marked `needs_review` and never stored without explicit user confirmation —
the platform is fully functional with Ollama unavailable.

## Database schema

PostgreSQL, migrated via Alembic (chain: `0001_baseline` → … →
`c2d8e4f6a951`), with UUID primary keys, foreign keys, CHECK constraints,
partial unique indexes, and JSONB provenance columns. Core tables:
`organizations`, `users`, `waste_listings`, `material_passports`,
`material_requirements`, `matches`, `offers`, `transactions`,
`recovery_records`, `impact_estimates`, `notifications`, `audit_logs`, plus
operational tables for graph sync runs, symbiosis runs, analytics runs,
regulation sources/items/refresh runs, assistant knowledge chunks/runs,
ingestion records, and ERP records. Every schema change is applied through a
migration; `alembic check` reports no drift.

## Security model

- JWT access tokens (HS256, configurable expiry) signed with a secret kept
  only in the backend `.env`; expired, tampered, or wrongly-signed tokens are
  rejected with 401.
- Passwords stored exclusively as Argon2 hashes.
- Organization-scoped authorization enforced server-side on every read and
  write; cross-organization access returns 403.
- Admin-only operations (graph sync, impact recompute, analytics recompute,
  ingestion/ERP imports, ERP runs-history export) are role-gated and audited
  through in-transaction audit events.
- Centralized error handlers return safe generic 409/500 responses; internals
  and credentials are never leaked, and third-party outages degrade to
  explicit, actionable messages.
- CORS is locked to the configured frontend origin; `.env`/`.env.local` are
  gitignored and never committed.

## API surface

All endpoints are prefixed with `/api` and documented via OpenAPI at
`http://localhost:8000/api/docs`. Capability groups:

- **Health:** `GET /api/health`, `GET /api/health/db`
- **Auth:** `POST /api/auth/login`, `GET /api/auth/me`; organizations
  `GET/PATCH /api/organizations/me`
- **Inventory:** `GET/POST /api/listings`, `GET/PATCH /api/listings/{id}`,
  `POST /api/listings/{id}/activate|archive`, passport endpoints under
  `/api/listings/{id}/passport`
- **Marketplace:** `GET /api/marketplace/listings`,
  `GET /api/marketplace/listings/{id}`, public passport read
- **Requirements & matching:** `GET/POST /api/requirements`,
  `PATCH /api/requirements/{id}`, `POST/GET /api/requirements/{id}/matches`,
  `GET /api/matching/evaluation`
- **Material intelligence:** `POST /api/ai/material-suggestions`,
  `POST /api/ai/listings/{id}/material-suggestions/accept`,
  `GET /api/ai/evaluation`
- **Dashboard:** `GET /api/dashboard/summary`
- **Pathways:** pathway ranking and explanation under `/api/pathways`,
  `GET /api/explain/pathway`
- **Impact & ESG:** `GET /api/impact/factors`, `POST /api/impact/recompute`,
  `GET /api/esg/dashboard`, `GET /api/esg/export`, trade endpoints under
  `/api/trades`
- **Explainability:** `GET /api/explain/status`,
  `GET /api/explain/match/{id}`, `GET /api/explain/impact/{id}`
- **Analytics:** `GET /api/analytics/marketplace`, CSV export, K-means runs,
  admin recompute
- **Graph:** `GET /api/graph/status`, admin `POST /api/graph/sync`,
  `GET /api/graph/explore`
- **Symbiosis:** `GET /api/symbiosis/opportunities`,
  `GET /api/symbiosis/evaluation`
- **Regulation:** sources, items, and refresh under `/api/regulation`
- **Assistant:** `POST /api/assistant/ask`, sources, evaluation, run history
- **Ingestion & ERP:** staged imports under `/api/ingestion`, ERP
  preview/confirm/export under `/api/erp`

Consistent status-code semantics: 401 unauthenticated, 403 insufficient
permissions, 404 missing, 409 conflicting state, 422 validation failure.

## Frontend

Role-aware navigation with client-side route guards (generators see inventory
tooling; buyers see requirements and matching; admins see operational
endpoints). Pages include login, dashboard, inventory (list, create,
detail/edit), marketplace (search, filters, public detail with passport),
requirements, matches (score breakdowns, material-fit/KNN chips, "Why this
match?" panels), pathways ("Why this pathway?" panels, exclusion lists,
sensitivity), symbiosis discovery, graph explorer, regulation feed, assistant,
analytics, and the ESG dashboard with drill-downs and CSV export. Loading,
empty, error, and success states are rendered throughout, and all displayed
business data comes from the API.

## Getting started

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL running locally on port 5432

### Database setup (one time)

```powershell
psql -U postgres -h localhost -c "CREATE USER recircle_app WITH PASSWORD 'local_dev_password';"
psql -U postgres -h localhost -c "CREATE DATABASE recircle OWNER recircle_app;"
```

### Backend

```powershell
cd code\backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # adjust credentials if yours differ
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m app.db.seed
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

- API docs: http://localhost:8000/api/docs
- Health: http://localhost:8000/api/health
- DB health: http://localhost:8000/api/health/db

### Frontend

```powershell
cd code\frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open http://localhost:3000 — the landing view reports live backend and
database status.


