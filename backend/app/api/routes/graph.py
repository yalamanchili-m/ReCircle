"""Graph exploration and sync API (blueprint Phase 6).

Every endpoint degrades gracefully: a disabled or unreachable Neo4j never
produces a 500 with internals and never blocks PostgreSQL workflows.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import GraphSyncRun, User
from app.services import audit
from app.services.graph import GraphUnavailable, graph_enabled
from app.services.graph.driver import get_driver

router = APIRouter()


@router.get("/graph/status")
def graph_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    settings_enabled = get_settings_neo4j_enabled()
    driver = get_driver()
    last_run = db.scalar(select(GraphSyncRun).order_by(GraphSyncRun.started_at.desc()))

    counts: dict[str, int] | None = None
    if driver is not None:
        try:
            with driver.session() as session:
                counts = {
                    label: session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
                    for label in ("Organization", "Listing", "Requirement", "MaterialType")
                }
        except Exception:
            counts = None

    return {
        "neo4j_configured": settings_enabled,
        "connected": driver is not None,
        "counts": counts,
        "last_sync": {
            "status": last_run.status,
            "error": last_run.error,
            "projection_version": last_run.projection_version,
            "started_at": last_run.started_at,
            "stats": last_run.stats,
        }
        if last_run
        else None,
    }


def get_settings_neo4j_enabled() -> bool:
    from app.core.config import get_settings

    return get_settings().neo4j_enabled


@router.post("/graph/sync")
def graph_sync(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Run the PostgreSQL -> Neo4j projection (admin only)."""
    from app.services.graph.sync import run_sync

    try:
        result = run_sync(db)
    except GraphUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j is disabled or unreachable; PostgreSQL data is unaffected",
        )
    audit.record_audit(
        db,
        actor=current_user,
        action="graph.sync",
        entity_type="graph",
        details={"stats": result.get("stats", {})},
    )
    db.commit()
    return result


@router.get("/graph/explore")
def graph_explore(
    node_id: str = Query(min_length=3, max_length=120),
    current_user: User = Depends(get_current_user),
) -> dict:
    """One-hop neighborhood of a node, with provenance on every edge."""
    driver = get_driver()
    if driver is None:
        return {
            "connected": False,
            "node": None,
            "relationships": [],
            "note": "Neo4j is disabled or unreachable; PostgreSQL data is unaffected",
        }
    try:
        with driver.session() as session:
            node_record = session.run(
                "MATCH (n {id: $id}) RETURN labels(n) AS labels, properties(n) AS props LIMIT 1",
                id=node_id,
            ).single(strict=False)
            if node_record is None:
                raise HTTPException(status_code=404, detail="Node not found in graph")
            rel_records = session.run(
                """
                MATCH (n {id: $id})-[r]-(m)
                RETURN type(r) AS rel_type, properties(r) AS rel_props,
                       labels(m) AS other_labels, properties(m) AS other_props
                LIMIT 100
                """,
                id=node_id,
            )
            relationships = [
                {
                    "rel_type": record["rel_type"],
                    "rel_properties": record["rel_props"],
                    "other_labels": record["other_labels"],
                    "other": record["other_props"],
                }
                for record in rel_records
            ]
            return {
                "connected": True,
                "node": {"labels": node_record["labels"], "properties": node_record["props"]},
                "relationships": relationships,
            }
    except HTTPException:
        raise
    except Exception:
        return {
            "connected": False,
            "node": None,
            "relationships": [],
            "note": "Graph query failed; PostgreSQL data is unaffected",
        }
