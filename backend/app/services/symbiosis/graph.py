"""In-memory symbiosis graph mirroring the Phase 6 Neo4j projection.

Same stable node ids (`org:`, `listing:`, `requirement:`, `material:`,
`application:`, `industry:`, `pathway:`) and the same fact edges, so BFS
paths found here are citable against the Neo4j projection. Pure Python,
deterministic, no live server required.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaterialRequirement, Match, Organization, WasteListing
from app.services.graph.sync import _resolve_material_type, _slug
from app.services.material_intelligence import taxonomy
from app.services.material_intelligence.taxonomy import TAXONOMY_VERSION

GRAPH_VERSION = "symbiosis-graph-v1"


@dataclass
class GraphNode:
    id: str
    labels: list[str]
    properties: dict


@dataclass
class GraphEdge:
    source: str
    target: str
    rel_type: str
    properties: dict = field(default_factory=dict)


class SymbiosisGraph:
    """Deterministic undirected weighted graph with typed edges."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self.adjacency: dict[str, dict[str, float]] = {}

    def add_node(self, node_id: str, labels: list[str], properties: dict | None = None) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(id=node_id, labels=labels, properties=properties or {})

    def add_edge(self, source: str, target: str, rel_type: str, properties: dict | None = None) -> None:
        self.edges.append(
            GraphEdge(source=source, target=target, rel_type=rel_type, properties=properties or {})
        )
        self.adjacency.setdefault(source, {})
        self.adjacency.setdefault(target, {})
        self.adjacency[source][target] = self.adjacency[source].get(target, 0.0) + 1.0
        self.adjacency[target][source] = self.adjacency[target].get(source, 0.0) + 1.0

    def snapshot_id(self) -> str:
        """Deterministic content hash identifying this graph snapshot."""
        import hashlib

        digest = hashlib.sha256()
        digest.update(GRAPH_VERSION.encode())
        digest.update(TAXONOMY_VERSION.encode())
        for node_id in sorted(self.nodes):
            digest.update(node_id.encode())
            digest.update(b"|")
        for edge in sorted(self.edges, key=lambda e: (e.source, e.target, e.rel_type)):
            digest.update(f"{edge.source}>{edge.rel_type}>{edge.target}".encode())
            digest.update(b"|")
        return f"{GRAPH_VERSION}:{digest.hexdigest()[:16]}"


def build_graph(db: Session) -> SymbiosisGraph:
    """Build the symbiosis graph from PostgreSQL facts plus curated taxonomy."""
    graph = SymbiosisGraph()

    organizations = {org.id: org for org in db.scalars(select(Organization)).all()}
    listings = list(db.scalars(select(WasteListing)).all())
    requirements = list(db.scalars(select(MaterialRequirement)).all())
    matches = list(db.scalars(select(Match).where(Match.status == "suggested")).all())

    for org in organizations.values():
        graph.add_node(f"org:{org.id}", ["Organization"], {
            "name": org.name,
            "organization_type": org.organization_type,
            "industry": org.industry,
            "city": org.city,
            "region": org.region,
        })

    for listing in listings:
        listing_key = f"listing:{listing.id}"
        org_key = f"org:{listing.organization_id}"
        graph.add_node(listing_key, ["Listing"], {
            "title": listing.title,
            "category": listing.category,
            "status": listing.status,
            "quantity": float(listing.quantity),
            "unit": listing.unit,
            "city": listing.city,
        })
        graph.add_edge(org_key, listing_key, "OWNS", {"provenance": "postgres_fact", "is_fact": True})

    for requirement in requirements:
        requirement_key = f"requirement:{requirement.id}"
        org_key = f"org:{requirement.organization_id}"
        graph.add_node(requirement_key, ["Requirement"], {
            "title": requirement.title,
            "category": requirement.category,
            "status": requirement.status,
            "min_quantity": float(requirement.min_quantity),
            "unit": requirement.unit,
        })
        graph.add_edge(org_key, requirement_key, "SEEKS", {"provenance": "postgres_fact", "is_fact": True})

    # Taxonomy nodes and curated edges (same resolution as the projection).
    for material_type in taxonomy.all_types():
        material_key = f"material:{material_type.type_id}"
        graph.add_node(material_key, ["MaterialType"], {
            "label": material_type.label,
            "category": material_type.category,
        })
        for application in material_type.applications:
            application_key = f"application:{_slug(application)}"
            graph.add_node(application_key, ["Application"], {"name": application})
            graph.add_edge(material_key, application_key, "SUITABLE_FOR", {
                "provenance": "curated_taxonomy", "is_fact": True,
            })
        for industry in material_type.industries:
            industry_key = f"industry:{_slug(industry)}"
            graph.add_node(industry_key, ["Industry"], {"name": industry})
            graph.add_edge(industry_key, material_key, "SUITED_INDUSTRY", {
                "provenance": "curated_taxonomy", "is_fact": True,
            })
        for pathway in taxonomy.CATEGORY_PATHWAY_DEFAULTS.get(material_type.category, []):
            pathway_key = f"pathway:{_slug(pathway)}"
            graph.add_node(pathway_key, ["CircularPathway"], {"name": pathway})
            graph.add_edge(material_key, pathway_key, "HAS_PATHWAY", {
                "provenance": "category_pathway_mapping", "is_fact": True,
            })

    # Resolve each listing/requirement to a material node and link it.
    for listing in listings:
        material_key, _label, resolution = _resolve_material_type(listing)
        graph.add_node(material_key, ["MaterialType"], {"resolved_via": resolution})
        graph.add_edge(f"listing:{listing.id}", material_key, "HAS_MATERIAL_TYPE", {
            "provenance": resolution, "is_fact": False,
        })
    for requirement in requirements:
        material_key, _label, resolution = _resolve_material_type(requirement)
        graph.add_node(material_key, ["MaterialType"], {"resolved_via": resolution})
        graph.add_edge(f"requirement:{requirement.id}", material_key, "WANTS_MATERIAL_TYPE", {
            "provenance": resolution, "is_fact": False,
        })

    # Inferred matches from the matching engine (non-fact edges).
    for match in matches:
        graph.add_edge(
            f"listing:{match.listing_id}",
            f"requirement:{match.requirement_id}",
            "INFERRED_MATCH",
            {
                "provenance": "algorithm",
                "is_fact": False,
                "algorithm_version": match.score_breakdown.get("algorithm_version", "unknown"),
            },
        )

    return graph
