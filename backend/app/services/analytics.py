"""Marketplace metrics + exploratory K-means clustering (blueprint Phase 11).

Database-backed, filtered, role/organization scoped. Aggregates never
leak private organization data: counts and region totals appear, org
names/ids never do (org-level sections are intentionally absent).

Clustering rules (blueprint blocks): features are documented, identifiers
and leakage-prone fields (ids, timestamps, statuses, org/ownership, text
titles) are excluded, numeric features are standardized and categorical
ones one-hot with explicit weights. Below MIN_SAMPLE_THRESHOLD the run is
recorded but returns an explicit `insufficient_data` empty state rather
than a fabricated cluster view. Clusters are exploratory only — never
authoritative material classes or safety predictions.
"""

import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, pstdev

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnalyticsRun,
    MaterialPassport,
    MaterialRequirement,
    Match,
    Offer,
    Transaction,
    User,
    WasteListing,
)
from app.services import kmeans as kmeans_engine
from app.services.kmeans import KMeansError

METRICS_VERSION = "marketplace-metrics-v1"
FEATURE_SCHEMA_VERSION = "market-features-v1"
RESULT_VERSION = kmeans_engine.RESULT_VERSION

CATEGORY_ORDER = [
    "metals",
    "plastics",
    "paper_cardboard",
    "wood",
    "glass",
    "textiles",
    "organics",
    "electronics",
    "chemicals",
    "other",
]

MIN_SAMPLE_THRESHOLD = 12
SILHOUETTE_CAP = 400
MAX_CLUSTER_K = 6
REGION_COVERAGE_RELIABLE = 0.80
TIME_SERIES_MIN_MONTHS = 2
DEFAULT_AUTO_K = "min(4, max(2, n // 10))"

MASS_UNIT_TO_TONNES = {"kg": Decimal("1") / Decimal("1000"), "tonne": Decimal("1")}

CLUSTERING_DISCLAIMERS = [
    "Clusters are exploratory visualizations over current marketplace data; "
    "they are NOT authoritative material classes, quality grades, or "
    "safety predictions.",
    "Assignments may change when listings are added, edited, or expired; "
    "with more data the same configuration can produce different clusters.",
    "Category is one-hot encoded with an explicit weight; numeric features "
    "are standardized. Identifiers, timestamps, statuses, and ownership "
    "fields are excluded from the feature set on purpose.",
]

METRICS_LIMITATIONS = [
    "All marketplace metrics are counts over platform records; they are "
    "not verified outcomes.",
    "Offer intentions and stored matches are activity signals, never "
    "guaranteed trades; completed transactions are the verified outcome.",
    "Region distribution is shown only when region data covers listings "
    f"at {int(REGION_COVERAGE_RELIABLE * 100)}%+; otherwise the section is "
    "omitted rather than showing a biased picture.",
    "Export reports aggregates only: no private organization data is "
    "included.",
]


# ------------------------------------------------------------ clustering


def _auto_k(n: int) -> int:
    return min(4, max(2, n // 10))


def _log1p(value: float) -> float:
    import math

    return math.log1p(max(0.0, value))


def _listing_rows(db: Session, sample_rows: list[WasteListing]) -> tuple[list[list[float]], list[dict], list[dict]]:
    """Feature vectors for the 'material clusters' subject.

    Feature schema (market-features-v1):
      - category one-hot (10 dims, weight 1.5) — categorical, documented
      - quantity_tonnes (log1p) — numeric, standardized; mass units only
      - price_per_unit (log1p, 0 when absent) — numeric, standardized
      - has_grade, has_material_passport — numeric 0/1 (standardized)

    Excluded on purpose (identifiers / leakage-prone): listing id, title,
    description, organization/ownership, status (only active rows are
    sampled), created/updated timestamps, city/country (handled via the
    documented geography section instead).
    """
    listing_ids = [row.id for row in sample_rows]
    passports = {
        row.listing_id
        for row in db.scalars(
            select(MaterialPassport).where(MaterialPassport.listing_id.in_(listing_ids))
        )
    } if listing_ids else set()

    categories = CATEGORY_ORDER
    numeric_names = ["quantity_tonnes", "price_per_unit", "has_grade", "has_passport"]
    schema: list[dict] = [
        {
            "feature": f"category_{category}",
            "kind": "one_hot",
            "weight": 1.5,
        }
        for category in categories
    ] + [
        {
            "feature": name,
            "kind": "numeric",
            "normalization": "standardize",
        }
        for name in numeric_names
    ]

    raw_numeric: list[list[float]] = []
    rows_meta: list[dict] = []
    for row in sample_rows:
        tonnes = None
        factor = MASS_UNIT_TO_TONNES.get(row.unit)
        if factor is not None:
            tonnes = float(row.quantity * factor)
        price = float(row.price_per_unit) if row.price_per_unit else 0.0
        raw_numeric.append(
            [
                _log1p(tonnes) if tonnes is not None else 0.0,
                _log1p(price),
                1.0 if row.grade else 0.0,
                1.0 if row.id in passports else 0.0,
            ]
        )
        rows_meta.append(
            {
                "category": row.category,
                "quantity_tonnes_available": tonnes is not None,
            }
        )

    standardized = _standardize(raw_numeric)
    vectors = []
    for index, sample in enumerate(rows_meta):
        vector: list[float] = []
        for category in categories:
            vector.append(1.5 if sample["category"] == category else 0.0)
        vector.extend(standardized[index])
        vectors.append(vector)
    return vectors, schema, rows_meta


def _requirement_rows(db: Session, sample_rows: list[MaterialRequirement]) -> tuple[list[list[float]], list[dict], list[dict], int]:
    """Feature vectors for the 'demand patterns' subject."""
    categories = CATEGORY_ORDER
    numeric_names = ["min_quantity_tonnes", "max_price_per_unit", "has_required_grade", "has_preferred_region"]
    schema = [
        {"feature": f"category_{category}", "kind": "one_hot", "weight": 1.5}
        for category in categories
    ] + [
        {"feature": name, "kind": "numeric", "normalization": "standardize"}
        for name in numeric_names
    ]
    raw_numeric, rows_meta, excluded_non_mass = [], [], 0
    for row in sample_rows:
        factor = MASS_UNIT_TO_TONNES.get(row.unit)
        if factor is None:
            excluded_non_mass += 1
            continue
        tonnes = float(row.min_quantity * factor)
        price = float(row.max_price_per_unit) if row.max_price_per_unit else 0.0
        raw_numeric.append(
            [
                _log1p(tonnes),
                _log1p(price),
                1.0 if row.required_grade else 0.0,
                1.0 if row.preferred_region else 0.0,
            ]
        )
        rows_meta.append({"category": row.category})
    standardized = _standardize(raw_numeric)
    vectors = []
    for index, sample in enumerate(rows_meta):
        vector: list[float] = []
        for category in categories:
            vector.append(1.5 if sample["category"] == category else 0.0)
        vector.extend(standardized[index])
        vectors.append(vector)
    return vectors, schema, rows_meta, excluded_non_mass


def _standardize(rows: list[list[float]]) -> list[list[float]]:
    """Column-wise z-score with a degenerate-column guard (std == 0 → 0)."""
    if not rows:
        return []
    columns = len(rows[0])
    means = [mean(row[c] for row in rows) for c in range(columns)]
    stds = [0.0 for _ in range(columns)]
    for c in range(columns):
        stds[c] = pstdev([row[c] for row in rows])
    standardized: list[list[float]] = []
    for row in rows:
        standardized.append(
            [
                0.0 if stds[c] == 0 else (row[c] - means[c]) / stds[c]
                for c in range(columns)
            ]
        )
    return standardized


def _centroid_highlights(vectors, assignments, schema):
    """Top-3 most distinguishing feature dimensions per cluster centroid."""
    result = kmeans_engine.deterministic_kmeans(vectors, len(set(assignments)))
    centroids = result["centroids"]
    global_mean = [
        sum(v[d] for v in vectors) / len(vectors)
        for d in range(len(vectors[0]))
    ]
    highlights = []
    for cluster, centroid in enumerate(centroids):
        deltas = [
            (centroid[d] - global_mean[d], schema[d]["feature"])
            for d in range(len(centroid))
        ]
        deltas.sort(key=lambda pair: (-abs(pair[0]), pair[1]))
        highlights.append(
            {
                "feature": deltas[0][1],
                "centroid_delta": round(deltas[0][0], 3),
                "runner_up": deltas[1][1],
                "runner_up_delta": round(deltas[1][0], 3),
            }
        )
    return highlights


def insufficient_payload(subject: str, sample: int, threshold: int) -> dict:
    return {
        "subject": subject,
        "insufficient_data": True,
        "sample_count": sample,
        "min_sample_threshold": threshold,
        "result": None,
        "empty_state": (
            f"Only {sample} sample rows are available; clustering needs at "
            f"least {threshold} and is skipped rather than showing an "
            "arbitrary partition."
        ),
    }


def run_kmeans(
    db: Session, actor: User, subject: str, k: int | None, category: str | None
) -> dict:
    """Deterministic clustering over the sampled subject; run recorded."""
    started = time.perf_counter()
    params: dict = {"subject": subject, "k": k, "category": category}
    try:
        if subject not in ("listings", "requirements"):
            raise KMeansError(
                "subject must be 'listings' (material clusters) or "
                "'requirements' (demand patterns)"
            )
        if k is not None and not 2 <= k <= MAX_CLUSTER_K:
            raise KMeansError(f"k must be within [2, {MAX_CLUSTER_K}], got {k}")

        if subject == "listings":
            query = select(WasteListing).where(WasteListing.status == "active")
            if category:
                query = query.where(WasteListing.category == category)
            sample_rows = list(
                db.scalars(query.order_by(WasteListing.created_at, WasteListing.id))
            )
            vectors, schema, rows_meta = _listing_rows(db, sample_rows)
            excluded = sum(
                1 for row in rows_meta if not row["quantity_tonnes_available"]
            )
        else:
            query = select(MaterialRequirement).where(
                MaterialRequirement.status == "active"
            )
            if category:
                query = query.where(MaterialRequirement.category == category)
            sample_rows = list(
                db.scalars(
                    query.order_by(MaterialRequirement.created_at, MaterialRequirement.id)
                )
            )
            vectors, schema, rows_meta, excluded = _requirement_rows(db, sample_rows)

        sample_count = len(vectors)
        used_k = k if k is not None else _auto_k(sample_count)

        if sample_count < MIN_SAMPLE_THRESHOLD:
            payload = insufficient_payload(
                subject, sample_count, MIN_SAMPLE_THRESHOLD
            )
            sampling_summary = {
                "sample_count": sample_count,
                "min_sample_threshold": MIN_SAMPLE_THRESHOLD,
                "sufficient": False,
                "excluded_rows": excluded,
                "basis": "active_rows",
                "warnings": [payload["empty_state"]],
            }
            run = _record_run(
                db, "kmeans", "success", params, schema, {}, sampling_summary,
                RESULT_VERSION, subject, actor, started,
            )
            return {
                **payload,
                "run_id": str(run.id),
                "result_version": RESULT_VERSION,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "feature_schema": schema,
                "disclaimers": CLUSTERING_DISCLAIMERS,
                "sampling_summary": sampling_summary,
                "versions": {
                    "algorithm": RESULT_VERSION,
                    "feature_schema": FEATURE_SCHEMA_VERSION,
                },
            }

        result = kmeans_engine.deterministic_kmeans(vectors, used_k)
        assignments = result["assignments"]
        counts: dict[int, int] = {}
        category_by_cluster: dict[int, list[str]] = {}
        for index, assigned in enumerate(assignments):
            counts[assigned] = counts.get(assigned, 0) + 1
            category_by_cluster.setdefault(assigned, []).append(rows_meta[index]["category"])

        clusters = []
        for cluster in sorted(counts):
            members_categories = category_by_cluster[cluster]
            dominant = max(set(members_categories), key=members_categories.count)
            share = counts[cluster] / sample_count
            clusters.append(
                {
                    "cluster": cluster,
                    "size": counts[cluster],
                    "share_of_sample": round(share, 4),
                    "dominant_category": dominant,
                    "dominant_category_share": round(
                        members_categories.count(dominant) / len(members_categories), 4
                    ),
                    "label": (
                        f"Dominant {dominant} ({members_categories.count(dominant)}"
                        f"/{len(members_categories)} rows)"
                    ),
                }
            )

        silhouette = None
        silhouette_note = "not computed"
        if sample_count <= SILHOUETTE_CAP:
            silhouette = kmeans_engine.silhouette_reduction(vectors, assignments)
            silhouette_note = "mean silhouette coefficient (higher is more separated)"
        else:
            silhouette_note = (
                f"sample exceeds {SILHOUETTE_CAP}; silhouette skipped to bound "
                "runtime (O(n^2))"
            )

        stats = {
            "clusters": clusters,
            "inertia": result["inertia"],
            "iterations": result["iterations"],
            "silhouette": silhouette,
            "silhouette_note": silhouette_note,
            "centroid_highlights": _centroid_highlights(vectors, assignments, schema),
        }
        sampling_summary = {
            "sample_count": sample_count,
            "min_sample_threshold": MIN_SAMPLE_THRESHOLD,
            "sufficient": True,
            "excluded_rows": excluded,
            "basis": "active_rows",
            "warnings": (
                ["Small sample: interpret clusters with caution; the sample "
                 "is near the minimum and clusters are unstable."]
                if sample_count < MIN_SAMPLE_THRESHOLD * 2
                else []
            ),
        }
        run = _record_run(
            db, "kmeans", "success", params, schema, stats, sampling_summary,
            RESULT_VERSION, subject, actor, started,
        )
        return {
            "subject": subject,
            "insufficient_data": False,
            "k": used_k,
            "k_requested": k,
            "k_default_rule": DEFAULT_AUTO_K if k is None else "explicit",
            "sample_count": sample_count,
            "run_id": str(run.id),
            "result_version": RESULT_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_schema": schema,
            "stats": stats,
            "sampling_summary": sampling_summary,
            "disclaimers": CLUSTERING_DISCLAIMERS,
            "versions": {
                "algorithm": RESULT_VERSION,
                "feature_schema": FEATURE_SCHEMA_VERSION,
            },
        }
    except KMeansError as error:
        _record_run(
            db, "kmeans", "failed", params, {}, {}, {"error": str(error)},
            RESULT_VERSION, subject, actor, started, error=str(error),
        )
        raise ValueError(str(error)) from error


def _record_run(
    db, kind, status, params, schema, stats, sampling, version, subject, actor,
    started, error=None,
) -> AnalyticsRun:
    run = AnalyticsRun(
        run_kind=kind,
        status=status,
        error=error,
        params=params,
        feature_schema=schema,
        stats=stats,
        sampling_summary=sampling,
        result_version=version,
        subjects=subject,
        runtime_ms=int((time.perf_counter() - started) * 1000),
        created_by=getattr(actor, "id", None),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    return run


# -------------------------------------------------------- marketplace metrics


def _period_bounds(period_from: str | None, period_to: str | None):
    if period_to:
        # A date period_to covers its entire day (end-of-day inclusive).
        to_bound = (
            datetime.fromisoformat(period_to)
            .replace(tzinfo=timezone.utc)
            .replace(hour=23, minute=59, second=59, microsecond=999999)
        )
    else:
        to_bound = datetime.now(timezone.utc)
    if period_from:
        from_bound = datetime.fromisoformat(period_from).replace(tzinfo=timezone.utc)
    else:
        from_bound = to_bound - timedelta(days=90)
    if from_bound > to_bound:
        raise ValueError("period_from must be before period_to")
    return from_bound, to_bound


def run_marketplace_metrics(
    db: Session, actor: User, *, period_from=None, period_to=None,
    category=None, industry=None,
) -> dict:
    started = time.perf_counter()
    from_bound, to_bound = _period_bounds(period_from, period_to)
    params = {
        "period_from": from_bound.date().isoformat(),
        "period_to": to_bound.date().isoformat(),
        "category": category,
        "industry": industry,
    }
    try:
        listing_query = select(WasteListing).where(
            WasteListing.created_at >= from_bound,
            WasteListing.created_at <= to_bound,
        )
        requirement_query = select(MaterialRequirement).where(
            MaterialRequirement.created_at >= from_bound,
            MaterialRequirement.created_at <= to_bound,
        )
        if category:
            listing_query = listing_query.where(WasteListing.category == category)
            requirement_query = requirement_query.where(
                MaterialRequirement.category == category
            )
        dp_listings = list(db.scalars(listing_query))
        dp_requirements = list(db.scalars(requirement_query))

        passports_by_listing: dict = {}
        if industry:
            wanted = industry.strip().lower()
            passports_by_listing = {
                row.listing_id: row
                for row in db.scalars(
                    select(MaterialPassport).where(
                        MaterialPassport.status == "active"
                    )
                )
                if wanted in [
                    entry.lower() for entry in (row.suitable_industries or [])
                ]
            }
            dp_listings = [
                row for row in dp_listings if row.id in passports_by_listing
            ]

        active_listings = [row for row in dp_listings if row.status == "active"]
        status_counts = {}
        for row in dp_listings:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1

        supply_demand_rows = []
        for cat in CATEGORY_ORDER:
            if category and cat != category:
                continue
            cat_listings = [row for row in active_listings if row.category == cat]
            cat_requirements = [
                row for row in dp_requirements if row.status == "active" and row.category == cat
            ]
            tonnes = 0.0
            requirement_tonnes = 0.0
            non_mass = 0
            for row in cat_listings:
                factor = MASS_UNIT_TO_TONNES.get(row.unit)
                if factor is None:
                    non_mass += 1
                else:
                    tonnes += float(row.quantity * factor)
            for row in cat_requirements:
                factor = MASS_UNIT_TO_TONNES.get(row.unit)
                if factor is not None:
                    requirement_tonnes += float(row.min_quantity * factor)
            supply_demand_rows.append(
                {
                    "category": cat,
                    "active_listings": len(cat_listings),
                    "active_listings_tonnes": round(tonnes, 3),
                    "non_mass_listings_excluded": non_mass,
                    "active_requirements": len(cat_requirements),
                    "active_requirements_min_tonnes": round(requirement_tonnes, 3),
                }
            )

        # Geography: shown only when region coverage supports it
        region_known = [row for row in active_listings if row.region]
        coverage = (
            len(region_known) / len(active_listings) if active_listings else 0.0
        )
        if active_listings and coverage >= REGION_COVERAGE_RELIABLE:
            regions: dict[str, int] = {}
            for row in region_known:
                regions[row.region] = regions.get(row.region, 0) + 1
            geography = {
                "available": True,
                "coverage": round(coverage, 3),
                "rows": [
                    {"region": region, "active_listings": count}
                    for region, count in sorted(
                        regions.items(), key=lambda pair: (-pair[1], pair[0])
                    )
                ],
            }
        else:
            geography = {
                "available": False,
                "coverage": round(coverage, 3),
                "reason": (
                    f"Only {len(region_known)}/{len(active_listings)} active "
                    "listings carry region data; reliable coverage is "
                    f"{int(REGION_COVERAGE_RELIABLE * 100)}%+ — section omitted "
                    "rather than showing a biased distribution."
                    if active_listings
                    else "No active listings in this period."
                ),
                "rows": [],
            }

        # Match/activity counts in period
        offers_in = db.scalars(
            select(Offer).where(
                Offer.created_at >= from_bound, Offer.created_at <= to_bound
            )
        ).all()
        transactions_in = db.scalars(
            select(Transaction).where(
                Transaction.created_at >= from_bound,
                Transaction.created_at <= to_bound,
            )
        ).all()
        matches_counts = db.scalar(
            select(func.count())
            .select_from(Match)
            .where(
                Match.generated_at >= from_bound, Match.generated_at <= to_bound
            )
        ) or 0
        match_activity = {
            "stored_matches": matches_counts,
            "offers_created": len(offers_in),
            "offers_accepted": sum(
                1 for offer in offers_in if offer.status == "accepted"
            ),
            "transactions_agreed": len(transactions_in),
            "transactions_completed": sum(
                1 for t in transactions_in if t.status == "completed"
            ),
        }

        # Pathway counts from the curated templates (deterministic, no usage data)
        from app.services.pathways import templates

        pathway_rows = []
        for cat in CATEGORY_ORDER:
            if category and cat != category:
                continue
            feasible = [
                pathway
                for pathway in templates.all_pathway_ids()
                if templates.is_feasible(pathway, cat, None)[0]
            ]
            pathway_rows.append(
                {
                    "category": cat,
                    "feasible_pathway_count": len(feasible),
                    "feasible_pathways": feasible,
                }
            )

        # Time series: monthly buckets, gated on date coverage
        months = _monthly_months(from_bound, to_bound)
        month_keys = {m.strftime("%Y-%m") for m in months}
        listings_by_month: dict[str, int] = {}
        requirements_by_month: dict[str, int] = {}
        completed_by_month: dict[str, int] = {}
        for row in dp_listings:
            key = row.created_at.strftime("%Y-%m")
            listings_by_month[key] = listings_by_month.get(key, 0) + 1
        for row in dp_requirements:
            key = row.created_at.strftime("%Y-%m")
            requirements_by_month[key] = requirements_by_month.get(key, 0) + 1
        for t in transactions_in:
            if t.status == "completed":
                key = t.created_at.strftime("%Y-%m")
                completed_by_month[key] = completed_by_month.get(key, 0) + 1
        data_months = (
            {key for key, value in listings_by_month.items() if value}
            | {key for key, value in requirements_by_month.items() if value}
            | {key for key, value in completed_by_month.items() if value}
        )
        covered_months = month_keys & data_months
        if (
            month_keys
            and len(month_keys) >= TIME_SERIES_MIN_MONTHS
            and len(data_months) >= TIME_SERIES_MIN_MONTHS
        ):
            time_series = {
                "available": True,
                "granularity": "month",
                "note": "Months with data only; empty months are omitted.",
                "rows": [
                    {
                        "month": key,
                        "listings_created": listings_by_month.get(key, 0),
                        "requirements_created": requirements_by_month.get(key, 0),
                        "transactions_completed": completed_by_month.get(key, 0),
                    }
                    for key in sorted(covered_months)
                ],
            }
        else:
            time_series = {
                "available": False,
                "granularity": "month",
                "reason": (
                    "Date coverage does not support a monthly series for this "
                    f"period (needs >= {TIME_SERIES_MIN_MONTHS} months with data; "
                    f"got {len(data_months)} months with data this period)."
                ),
                "rows": [],
            }

        total_active = len(active_listings)
        warnings = []
        if total_active == 0:
            warnings.append(
                "No active listings in this period/filter: empty state, no "
                "fabricated metrics."
            )
        elif total_active < 10:
            warnings.append(
                f"Small marketplace sample ({total_active} active listings); "
                "supply/demand ratios for small categories are unreliable."
            )
        if industry and not passports_by_listing:
            warnings.append(
                "Industry filter is based on material passports; no passports "
                "carry that industry yet, so the report is empty by design."
            )

        stats = {
            "listings": status_counts,
            "supply_demand_rows": supply_demand_rows,
            "geography": geography,
            "match_activity": match_activity,
            "pathway_rows": pathway_rows,
            "time_series": time_series,
            "warnings": warnings,
        }
        _record_run(
            db, "marketplace_metrics", "success", params, {}, stats,
            {"active_listings": total_active}, METRICS_VERSION,
            "marketplace", actor, started,
        )
        return {
            "version": METRICS_VERSION,
            "period": {
                "from": from_bound.date().isoformat(),
                "to": to_bound.date().isoformat(),
                "basis": "created_at of records within the selected window",
            },
            "filters": {"category": category, "industry": industry},
            "metrics": stats,
            "limitations": METRICS_LIMITATIONS,
        }
    except ValueError as error:
        _record_run(
            db, "marketplace_metrics", "failed", params, {}, {}, {"error": str(error)},
            METRICS_VERSION, "marketplace", actor, started, error=str(error),
        )
        raise


def _monthly_months(start: datetime, end: datetime) -> list[date]:
    months = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    guard = 0
    while cursor <= last and guard < 240:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=8)).replace(day=1)
        guard += 1
    return months


def marketplace_metrics_csv(payload: dict) -> str:
    """CSV export of aggregates only (no org identity, private data excluded)."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "key", "value"])
    metrics = payload["metrics"]
    writer.writerow(["period", "from", payload["period"]["from"]])
    writer.writerow(["period", "to", payload["period"]["to"]])
    for status, count in sorted(metrics["listings"].items()):
        writer.writerow(["listings", status, count])
    for row in metrics["supply_demand_rows"]:
        writer.writerow(
            [
                "supply_demand",
                row["category"],
                f"listings={row['active_listings']} tonnes={row['active_listings_tonnes']}"
                f" requirements={row['active_requirements']} req_tonnes={row['active_requirements_min_tonnes']}",
            ]
        )
    if metrics["geography"]["available"]:
        for row in metrics["geography"]["rows"]:
            writer.writerow(["region", row["region"], row["active_listings"]])
    for key, value in sorted(metrics["match_activity"].items()):
        writer.writerow(["activity", key, value])
    for row in metrics["pathway_rows"]:
        writer.writerow(
            [
                "pathways",
                row["category"],
                row["feasible_pathway_count"],
            ]
        )
    if metrics["time_series"]["available"]:
        for row in metrics["time_series"]["rows"]:
            writer.writerow(
                [
                    "time_series",
                    row["month"],
                    f"listings={row['listings_created']}"
                    f" requirements={row['requirements_created']}"
                    f" completed={row['transactions_completed']}",
                ]
            )
    return buffer.getvalue()
