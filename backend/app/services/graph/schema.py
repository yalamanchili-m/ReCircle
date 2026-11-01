"""Graph schema: labels, constraints, and indexes.

Applied idempotently (IF NOT EXISTS semantics) so repeat runs and repeat
syncs are safe.
"""

from .driver import require_driver

# Uniqueness constraints (`c_*`) and query indexes (`idx_*`). Constraints in
# Neo4j 5 back indexes, so separate term indexes are only kept where they
# serve non-unique lookups.
CONSTRAINTS = [
    ("c_org_id", "Organization", "id"),
    ("c_listing_id", "Listing", "id"),
    ("c_requirement_id", "Requirement", "id"),
    ("c_material_id", "MaterialType", "id"),
    ("c_application_id", "Application", "id"),
    ("c_industry_id", "Industry", "id"),
    ("c_pathway_id", "CircularPathway", "id"),
]

INDEXES = [
    ("idx_listing_category", "Listing", "category"),
    ("idx_listing_location", "Listing", "location_key"),
    ("idx_material_category", "MaterialType", "category"),
]


def ensure_graph_schema(driver=None) -> int:
    """Create constraints and indexes if missing. Returns statements applied."""
    driver = driver or require_driver()
    applied = 0
    with driver.session() as session:
        for name, label, column in CONSTRAINTS:
            session.run(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{column} IS UNIQUE"
            )
            applied += 1
        for name, label, column in INDEXES:
            session.run(f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{column})")
            applied += 1
    return applied
