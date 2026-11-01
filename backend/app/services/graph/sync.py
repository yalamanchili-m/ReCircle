"""Idempotent PostgreSQL -> Neo4j projection (blueprint Phase 6).

Rules:
- MERGE on stable ids only (`org:<uuid>`, `listing:<uuid>`, ...) so repeated
  syncs never create duplicates.
- Every node and relationship carries source/evidence/provenance and the
  projection version.
- Facts come from PostgreSQL or the curated taxonomy. Model-generated links
  (match snapshots) are synced as `INFERRED_MATCH` with `is_fact=false` and
  `provenance=algorithm` — never asserted as facts.
- Material type resolution is deterministic (taxonomy aliases) with a
  documented `Unclassified <category>` fallback.
- Sync runs are tracked in PostgreSQL (`graph_sync_runs`), including
  failures, so status is queryable even when the graph is down.
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MaterialRequirement, WasteListing
from app.services.material_intelligence import taxonomy
from app.services.material_intelligence.taxonomy import TAXONOMY_VERSION

from .driver import GraphUnavailable, require_driver
from .schema import ensure_graph_schema

logger = logging.getLogger("app.graph")

PROJECTION_VERSION = "graph-projection-v1"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "unknown"


def _resolve_material_type(listing_or_requirement) -> tuple[str, str, str]:
    """Returns (material_id, label, provenance_kind) deterministically."""
    entry = listing_or_requirement
    text = " ".join(
        part
        for part in (
            getattr(entry, "title", None),
            getattr(entry, "description", None),
            getattr(entry, "material_name", None),
            getattr(entry, "composition", None),
        )
        if part
    )
    resolved = taxonomy.resolve_by_alias(text)
    if resolved is not None:
        material, _alias = resolved
        return f"material:{material.type_id}", material.label, "taxonomy_v1_deterministic"
    category = listing_or_requirement.category
    return f"material:unclassified-{_slug(category)}", f"Unclassified {category}", "fallback_category"


def _collect_from_postgres(db: Session) -> dict:
    from app.models import Organization

    listings = db.scalars(select(WasteListing)).all()
    requirements = db.scalars(select(MaterialRequirement)).all()
    matches = db.scalars(
        select(Match).where(Match.status == "suggested")
    ).all()
    organizations = {
        org.id: org for org in db.scalars(select(Organization)).all()
    }
    return {
        "organizations": organizations,
        "listings": list(listings),
        "requirements": list(requirements),
        "matches": list(matches),
    }


def run_sync(db: Session, dry_run: bool = False) -> dict:
    """Project PostgreSQL facts into Neo4j. Returns a run summary.

    Raises GraphUnavailable when the graph is disabled/unreachable; the
    failure is still recorded in `graph_sync_runs` before re-raising.
    """
    started = datetime.now(timezone.utc)
    data = _collect_from_postgres(db)

    try:
        driver = require_driver()
    except GraphUnavailable:
        _record_run(db, status="failed", error="Neo4j is disabled or unreachable", stats={})
        raise

    try:
        ensure_graph_schema(driver)
        stats = _apply_projection(driver, data)
        _record_run(db, status="success", error=None, stats=stats)
        return {
            "status": "success",
            "projection_version": PROJECTION_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "stats": stats,
            "dry_run": dry_run,
        }
    except Exception as exc:
        _record_run(db, status="failed", error=str(exc), stats={})
        raise


def _record_run(db: Session, *, status: str, error: str | None, stats: dict) -> None:
    from app.models import GraphSyncRun

    db.add(
        GraphSyncRun(
            status=status,
            error=error,
            stats=stats,
            projection_version=PROJECTION_VERSION,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def _apply_projection(driver, data: dict) -> dict:
    counts = {
        "organizations": 0,
        "listings": 0,
        "requirements": 0,
        "material_types": 0,
        "applications": 0,
        "industries": 0,
        "pathways": 0,
        "inferred_matches": 0,
    }
    seen_materials: set[str] = set()
    seen_applications: set[str] = set()
    seen_industries: set[str] = set()
    seen_pathways: set[str] = set()

    base = {"projection_version": PROJECTION_VERSION, "taxonomy_version": TAXONOMY_VERSION}

    with driver.session() as session:
        orgs_seen: dict[str, dict] = {}

        def ensure_org(org_id, name, org_type=None, city=None, region=None) -> str:
            org_key = f"org:{org_id}"
            if org_key not in orgs_seen:
                orgs_seen[org_key] = {"name": name}
                session.run(
                    """
                    MERGE (o:Organization {id: $id})
                    ON CREATE SET o.created_at = $now
                    SET o.name = $name,
                        o.organization_type = coalesce($org_type, o.organization_type),
                        o.location_key = coalesce($location_key, o.location_key),
                        o.provenance = 'postgres_fact',
                        o.projection_version = $projection_version
                    """,
                    id=org_key,
                    name=name,
                    org_type=org_type,
                    location_key=" ".join(filter(None, [city, region])),
                    now=datetime.now(timezone.utc).isoformat(),
                    **base,
                )
                counts["organizations"] += 1
            return org_key

        def ensure_material(material_id: str, label: str, category: str, provenance_kind: str) -> str:
            if material_id not in seen_materials:
                session.run(
                    """
                    MERGE (m:MaterialType {id: $id})
                    ON CREATE SET m.created_at = $now
                    SET m.label = $label,
                        m.category = $category,
                        m.resolution = $resolution,
                        m.provenance = $provenance,
                        m.projection_version = $projection_version,
                        m.taxonomy_version = $taxonomy_version
                    """,
                    id=material_id,
                    label=label,
                    category=category,
                    resolution=provenance_kind,
                    provenance="curated_taxonomy" if provenance_kind != "fallback_category" else "fallback",
                    now=datetime.now(timezone.utc).isoformat(),
                    **base,
                )
                seen_materials.add(material_id)
                counts["material_types"] += 1
            return material_id

        def ensure_application(name: str) -> str:
            app_id = f"application:{_slug(name)}"
            if app_id not in seen_applications:
                session.run(
                    """
                    MERGE (a:Application {id: $id})
                    ON CREATE SET a.created_at = $now, a.provenance = 'curated_taxonomy',
                                  a.projection_version = $projection_version
                    SET a.name = $name
                    """,
                    id=app_id,
                    name=name,
                    now=datetime.now(timezone.utc).isoformat(),
                    projection_version=PROJECTION_VERSION,
                )
                seen_applications.add(app_id)
                counts["applications"] += 1
            return app_id

        def ensure_industry(name: str) -> str:
            industry_id = f"industry:{_slug(name)}"
            if industry_id not in seen_industries:
                session.run(
                    """
                    MERGE (i:Industry {id: $id})
                    ON CREATE SET i.created_at = $now, i.provenance = 'curated_taxonomy',
                                  i.projection_version = $projection_version
                    SET i.name = $name
                    """,
                    id=industry_id,
                    name=name,
                    now=datetime.now(timezone.utc).isoformat(),
                    projection_version=PROJECTION_VERSION,
                )
                seen_industries.add(industry_id)
                counts["industries"] += 1
            return industry_id

        def ensure_pathway(name: str) -> str:
            pathway_id = f"pathway:{_slug(name)}"
            if pathway_id not in seen_pathways:
                session.run(
                    """
                    MERGE (p:CircularPathway {id: $id})
                    ON CREATE SET p.created_at = $now, p.provenance = 'category_pathway_mapping',
                                  p.projection_version = $projection_version
                    SET p.name = $name
                    """,
                    id=pathway_id,
                    name=name,
                    now=datetime.now(timezone.utc).isoformat(),
                    projection_version=PROJECTION_VERSION,
                )
                seen_pathways.add(pathway_id)
                counts["pathways"] += 1
            return pathway_id

        # --- Listings and their facts -----------------------------------
        for listing in data["listings"]:
            org = data["organizations"][listing.organization_id]
            org_key = ensure_org(
                org.id,
                org.name,
                org.organization_type,
                org.city,
                org.region,
            )
            listing_key = f"listing:{listing.id}"
            session.run(
                """
                MERGE (l:Listing {id: $id})
                ON CREATE SET l.created_at = $now
                SET l.title = $title,
                    l.category = $category,
                    l.status = $status,
                    l.quantity = $quantity,
                    l.unit = $unit,
                    l.location_key = $location_key,
                    l.provenance = 'postgres_fact',
                    l.projection_version = $projection_version
                """,
                id=listing_key,
                title=listing.title,
                category=listing.category,
                status=listing.status,
                quantity=float(listing.quantity),
                unit=listing.unit,
                location_key=" ".join(filter(None, [listing.city, listing.region])),
                now=datetime.now(timezone.utc).isoformat(),
                projection_version=PROJECTION_VERSION,
            )
            counts["listings"] += 1

            session.run(
                """
                MATCH (o:Organization {id: $org_id}), (l:Listing {id: $listing_id})
                MERGE (o)-[r:OWNS]->(l)
                SET r.provenance = 'postgres_fact', r.projection_version = $projection_version
                """,
                org_id=org_key,
                listing_id=listing_key,
                projection_version=PROJECTION_VERSION,
            )

            material_id, material_label, provenance_kind = _resolve_material_type(listing)
            ensure_material(material_id, material_label, listing.category, provenance_kind)
            session.run(
                """
                MATCH (l:Listing {id: $listing_id}), (m:MaterialType {id: $material_id})
                MERGE (l)-[r:HAS_MATERIAL_TYPE]->(m)
                SET r.provenance = $provenance,
                    r.taxonomy_version = $taxonomy_version,
                    r.projection_version = $projection_version
                """,
                listing_id=listing_key,
                material_id=material_id,
                provenance=provenance_kind,
                taxonomy_version=TAXONOMY_VERSION,
                projection_version=PROJECTION_VERSION,
            )

            # Curated taxonomy edges for the resolved material type.
            entry = taxonomy.get_type(material_id.split(":", 1)[1]) if provenance_kind != "fallback_category" else None
            if entry is not None:
                for application in entry.applications:
                    app_id = ensure_application(application)
                    session.run(
                        """
                        MATCH (m:MaterialType {id: $material_id}), (a:Application {id: $app_id})
                        MERGE (m)-[r:SUITABLE_FOR]->(a)
                        SET r.provenance = 'curated_taxonomy', r.taxonomy_version = $taxonomy_version,
                            r.projection_version = $projection_version
                        """,
                        material_id=material_id,
                        app_id=app_id,
                        taxonomy_version=TAXONOMY_VERSION,
                        projection_version=PROJECTION_VERSION,
                    )
                for industry in entry.industries:
                    industry_id = ensure_industry(industry)
                    session.run(
                        """
                        MATCH (m:MaterialType {id: $material_id}), (i:Industry {id: $industry_id})
                        MERGE (m)-[r:SUITED_INDUSTRY]->(i)
                        SET r.provenance = 'curated_taxonomy', r.taxonomy_version = $taxonomy_version,
                            r.projection_version = $projection_version
                        """,
                        material_id=material_id,
                        industry_id=industry_id,
                        taxonomy_version=TAXONOMY_VERSION,
                        projection_version=PROJECTION_VERSION,
                    )
            for pathway in taxonomy.CATEGORY_PATHWAY_DEFAULTS.get(listing.category, []):
                pathway_id = ensure_pathway(pathway)
                session.run(
                    """
                    MATCH (m:MaterialType {id: $material_id}), (p:CircularPathway {id: $pathway_id})
                    MERGE (m)-[r:HAS_PATHWAY]->(p)
                    SET r.provenance = 'category_pathway_mapping',
                        r.taxonomy_version = $taxonomy_version,
                        r.projection_version = $projection_version
                    """,
                    material_id=material_id,
                    pathway_id=pathway_id,
                    taxonomy_version=TAXONOMY_VERSION,
                    projection_version=PROJECTION_VERSION,
                )

        # --- Requirements and their facts --------------------------------
        for requirement in data["requirements"]:
            org = data["organizations"][requirement.organization_id]
            org_key = ensure_org(
                org.id,
                org.name,
                org.organization_type,
                org.city,
                org.region,
            )
            requirement_key = f"requirement:{requirement.id}"
            session.run(
                """
                MERGE (r:Requirement {id: $id})
                ON CREATE SET r.created_at = $now
                SET r.title = $title,
                    r.category = $category,
                    r.status = $status,
                    r.min_quantity = $min_quantity,
                    r.unit = $unit,
                    r.provenance = 'postgres_fact',
                    r.projection_version = $projection_version
                """,
                id=requirement_key,
                title=requirement.title,
                category=requirement.category,
                status=requirement.status,
                min_quantity=float(requirement.min_quantity),
                unit=requirement.unit,
                now=datetime.now(timezone.utc).isoformat(),
                projection_version=PROJECTION_VERSION,
            )
            counts["requirements"] += 1

            session.run(
                """
                MATCH (o:Organization {id: $org_id}), (r:Requirement {id: $requirement_id})
                MERGE (o)-[rel:SEEKS]->(r)
                SET rel.provenance = 'postgres_fact', rel.projection_version = $projection_version
                """,
                org_id=org_key,
                requirement_id=requirement_key,
                projection_version=PROJECTION_VERSION,
            )

            material_id, material_label, provenance_kind = _resolve_material_type(requirement)
            ensure_material(material_id, material_label, requirement.category, provenance_kind)
            session.run(
                """
                MATCH (r:Requirement {id: $requirement_id}), (m:MaterialType {id: $material_id})
                MERGE (r)-[rel:WANTS_MATERIAL_TYPE]->(m)
                SET rel.provenance = $provenance,
                    rel.taxonomy_version = $taxonomy_version,
                    rel.projection_version = $projection_version
                """,
                requirement_id=requirement_key,
                material_id=material_id,
                provenance=provenance_kind,
                taxonomy_version=TAXONOMY_VERSION,
                projection_version=PROJECTION_VERSION,
            )

        # --- Match snapshots: algorithm-generated, never facts -----------
        for match in data["matches"]:
            session.run(
                """
                MATCH (r:Requirement {id: $requirement_id}), (l:Listing {id: $listing_id})
                MERGE (r)-[rel:INFERRED_MATCH]->(l)
                SET rel.score = $score,
                    rel.algorithm_version = $algorithm_version,
                    rel.provenance = 'algorithm',
                    rel.is_fact = false,
                    rel.projection_version = $projection_version
                """,
                requirement_id=f"requirement:{match.requirement_id}",
                listing_id=f"listing:{match.listing_id}",
                score=float(match.score),
                algorithm_version=match.score_breakdown.get("algorithm_version", "unknown"),
                projection_version=PROJECTION_VERSION,
            )
            counts["inferred_matches"] += 1

    return counts
