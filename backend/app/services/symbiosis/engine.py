"""Industrial symbiosis discovery (blueprint Phase 7).

Combines graph structure (BFS proximity, PageRank hubs, Louvain clusters)
with material compatibility and availability. Graph proximity alone is never
a recommendation: hard category/status constraints run first, and every
candidate carries evidence, provenance, and explicit limitations.
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import SymbiosisRun, WasteListing, MaterialRequirement
from app.services.material_intelligence import taxonomy
from app.services.symbiosis import algorithms
from app.services.symbiosis.graph import SymbiosisGraph, build_graph

logger = logging.getLogger("app.symbiosis")

DISCOVERY_VERSION = "symbiosis-discovery-v1"

# Documented fixed weights (blueprint: combine structure with compatibility
# and availability; graph proximity alone is not a valid recommendation).
CONFIDENCE_WEIGHTS = {
    "material_fit": 0.45,
    "availability": 0.25,
    "graph_proximity": 0.20,
    "cluster_membership": 0.10,
}

LIMITATIONS = [
    "Inferred relationships are potential opportunities requiring validation, "
    "not verified trades.",
    "Graph proximity is a structural signal only; it does not imply chemical, "
    "legal, or process safety.",
    "Compatibility is estimated from taxonomy aliases and term similarity on "
    "user-entered text; it is not a materials-science assessment.",
    "Availability reflects listed quantities and open requirement status at "
    "run time and may be stale.",
]

MAX_DEPTH_CAP = 6


def _resolve_material_text(entry) -> str:
    return " ".join(
        part
        for part in (
            getattr(entry, "title", None),
            getattr(entry, "material_name", None),
            getattr(entry, "composition", None),
            getattr(entry, "description", None),
        )
        if part
    )


def _material_fit(listing: WasteListing, requirement: MaterialRequirement) -> float:
    """0-1 compatibility from taxonomy alias equality or term cosine."""
    listing_text = _resolve_material_text(listing)
    requirement_text = _resolve_material_text(requirement)
    resolved_listing = taxonomy.resolve_by_alias(listing_text)
    resolved_requirement = taxonomy.resolve_by_alias(requirement_text)
    if resolved_listing is not None and resolved_requirement is not None:
        if resolved_listing[0].type_id == resolved_requirement[0].type_id:
            return 1.0
        if resolved_listing[0].category == resolved_requirement[0].category:
            return max(0.0, min(1.0, _cosine_text(listing_text, requirement_text)))
        return 0.0
    return max(0.0, min(1.0, _cosine_text(listing_text, requirement_text)))


def _cosine_text(left: str, right: str) -> float:
    from app.services.material_intelligence import similarity as sim

    return sim._cosine(
        sim._term_frequencies(sim.tokenize(left)),
        sim._term_frequencies(sim.tokenize(right)),
    )


def _availability(listing: WasteListing, requirement: MaterialRequirement) -> float:
    """How well the listing's remaining quantity covers the requirement."""
    if requirement.min_quantity <= 0 or listing.quantity <= 0:
        return 0.0
    coverage = float(listing.quantity) / float(requirement.min_quantity)
    return max(0.0, min(1.0, coverage))


def _edge_view_from_map(
    edges_by_pair: dict[tuple[str, str], dict], path: list[str]
) -> list[dict]:
    """Resolve a node path into the concrete edges that realize it."""
    view = []
    for source, target in zip(path, path[1:]):
        edge = edges_by_pair.get((source, target))
        if edge:
            view.append({
                "from": source,
                "to": target,
                "rel_type": edge["rel_type"],
                "provenance": edge["properties"].get("provenance"),
                "is_fact": edge["properties"].get("is_fact", False),
            })
    return view


def discover_opportunities(
    db: Session,
    *,
    category: str | None = None,
    region: str | None = None,
    max_depth: int = 4,
    min_confidence: float = 0.0,
    limit: int = 20,
) -> dict:
    """Discover candidate symbiosis links; records a SymbiosisRun row."""
    max_depth = max(1, min(max_depth, MAX_DEPTH_CAP))
    limit = max(1, min(limit, 100))
    started_at = datetime.now(timezone.utc)
    started_tick = time.perf_counter()

    params = {
        "category": category,
        "region": region,
        "max_depth": max_depth,
        "min_confidence": min_confidence,
        "limit": limit,
    }

    try:
        result, stats = _run_discovery(
            db, category=category, region=region, max_depth=max_depth,
            min_confidence=min_confidence, limit=limit,
        )
        _record_run(db, status="success", error=None, params=params, stats=stats,
                    started_at=started_at, runtime_ms=int((time.perf_counter() - started_tick) * 1000))
        return {**result, "run": {"status": "success", **stats_public(stats), "params": params}}
    except Exception as exc:
        _record_run(db, status="failed", error=str(exc), params=params, stats={},
                    started_at=started_at, runtime_ms=int((time.perf_counter() - started_tick) * 1000))
        raise


def stats_public(stats: dict) -> dict:
    return {
        "graph_snapshot_id": stats.get("graph_snapshot_id"),
        "candidates": stats.get("candidates"),
        "runtime_ms": stats.get("runtime_ms"),
        "versions": stats.get("versions"),
    }


def _run_discovery(
    db: Session,
    *,
    category: str | None,
    region: str | None,
    max_depth: int,
    min_confidence: float,
    limit: int,
) -> tuple[dict, dict]:
    graph = build_graph(db)
    snapshot_id = graph.snapshot_id()

    edges_by_pair: dict[tuple[str, str], dict] = {}
    for edge in graph.edges:
        for key in ((edge.source, edge.target), (edge.target, edge.source)):
            edges_by_pair.setdefault(key, {
                "rel_type": edge.rel_type,
                "properties": edge.properties,
            })

    pagerank = algorithms.pagerank(graph)
    communities = algorithms.louvain_communities(graph)

    listings_query = db.query(WasteListing).filter(
        WasteListing.status == "active",
        WasteListing.quantity > 0,
    )
    if category:
        listings_query = listings_query.filter(WasteListing.category == category)
    active_listings = listings_query.all()

    requirements_query = db.query(MaterialRequirement).filter(
        MaterialRequirement.status == "active",
        MaterialRequirement.min_quantity > 0,
    )
    if category:
        requirements_query = requirements_query.filter(
            MaterialRequirement.category == category
        )
    if region:
        listings_query = listings_query.filter(WasteListing.region == region)
        requirements_query = requirements_query.filter(
            MaterialRequirement.preferred_region == region
        )
    requirements = requirements_query.all()

    from app.models import Organization

    organization_names = {
        str(org.id): org.name for org in db.query(Organization).all()
    }

    # Group requirements by category so each listing only compares against
    # same-category requirements (category is a hard constraint).
    requirements_by_category: dict[str, list] = {}
    for requirement in requirements:
        requirements_by_category.setdefault(requirement.category, []).append(requirement)

    # BFS is cached per producer org and paths per producer/consumer pair:
    # structural lookups must not dominate runtime.
    bfs_cache: dict[str, tuple[dict, dict]] = {}
    path_cache: dict[tuple[str, str], list[str]] = {}

    def _path_between(producer_key: str, consumer_key: str) -> list[str]:
        cache_key = (producer_key, consumer_key)
        if cache_key not in path_cache:
            if producer_key not in bfs_cache:
                bfs_cache[producer_key] = algorithms.bfs_from_source(
                    graph, producer_key, max_depth=max_depth
                )
            depth, parents = bfs_cache[producer_key]
            paths = algorithms.reconstruct_path(producer_key, consumer_key, depth, parents)
            path_cache[cache_key] = paths[0] if paths else []
        return path_cache[cache_key]

    candidates: list[dict] = []
    for listing in active_listings:
        for requirement in requirements_by_category.get(listing.category, []):
            # Hard constraint: category must match exactly (never overridden
            # by graph structure).
            fit = _material_fit(listing, requirement)
            availability = _availability(listing, requirement)

            producer_key = f"org:{listing.organization_id}"
            consumer_key = f"org:{requirement.organization_id}"
            path = _path_between(producer_key, consumer_key)
            proximity = 1.0 / len(path) if path else 0.0

            cluster = 0.0
            shared_cluster = None
            if (
                producer_key in communities
                and consumer_key in communities
                and communities[producer_key] == communities[consumer_key]
            ):
                cluster = 1.0
                shared_cluster = communities[producer_key]

            confidence = (
                CONFIDENCE_WEIGHTS["material_fit"] * fit
                + CONFIDENCE_WEIGHTS["availability"] * availability
                + CONFIDENCE_WEIGHTS["graph_proximity"] * proximity
                + CONFIDENCE_WEIGHTS["cluster_membership"] * cluster
            )
            if confidence < min_confidence:
                continue

            evidence = {
                "path": path,
                "path_edges": _edge_view_from_map(edges_by_pair, path) if path else [],
                "path_depth": len(path) - 1 if path else None,
                "shared_cluster": shared_cluster,
                "hub_pagerank": {
                    node: round(pagerank.get(node, 0.0), 8)
                    for node in (producer_key, consumer_key)
                },
            }
            candidates.append({
                "producer_organization_id": str(listing.organization_id),
                "producer_organization_name": organization_names.get(
                    str(listing.organization_id)
                ),
                "consumer_organization_id": str(requirement.organization_id),
                "consumer_organization_name": organization_names.get(
                    str(requirement.organization_id)
                ),
                "listing_id": str(listing.id),
                "listing_title": listing.title,
                "requirement_id": str(requirement.id),
                "requirement_title": requirement.title,
                "category": listing.category,
                "material_fit": round(fit, 4),
                "availability": round(availability, 4),
                "graph_proximity": round(proximity, 4),
                "cluster_membership": shared_cluster,
                "confidence": round(confidence, 4),
                "evidence": evidence,
                "status": "inferred_opportunity_requires_validation",
            })

    candidates.sort(
        key=lambda c: (-c["confidence"], c["listing_id"], c["requirement_id"])
    )
    candidates = candidates[:limit]

    hubs = sorted(
        (
            {"node": node, "pagerank": round(score, 8)}
            for node, score in pagerank.items()
            if node.startswith("material:") or node.startswith("industry:")
        ),
        key=lambda h: (-h["pagerank"], h["node"]),
    )[:5]

    cluster_summary: dict[int, int] = {}
    for community in communities.values():
        cluster_summary[community] = cluster_summary.get(community, 0) + 1

    stats = {
        "graph_snapshot_id": snapshot_id,
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "candidates": len(candidates),
        "cluster_count": len(cluster_summary),
        "versions": {
            "discovery": DISCOVERY_VERSION,
            "taxonomy": taxonomy.TAXONOMY_VERSION,
            "weights": CONFIDENCE_WEIGHTS,
        },
    }
    result = {
        "opportunities": candidates,
        "graph": {
            "snapshot_id": snapshot_id,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "top_hubs": hubs,
            "clusters": cluster_summary,
        },
        "limitations": LIMITATIONS,
    }
    return result, stats


def _record_run(db, *, status, error, params, stats, started_at, runtime_ms):
    db.add(
        SymbiosisRun(
            status=status,
            error=error,
            params=params,
            stats=stats,
            graph_snapshot_id=stats.get("graph_snapshot_id") if stats else None,
            discovery_version=DISCOVERY_VERSION,
            taxonomy_version=taxonomy.TAXONOMY_VERSION,
            runtime_ms=runtime_ms,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
