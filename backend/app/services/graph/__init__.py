"""Neo4j graph projection package (blueprint Phase 6).

Neo4j is an optional projection of PostgreSQL facts. Every function degrades
gracefully when Neo4j is disabled or unreachable: PostgreSQL workflows are
never blocked or corrupted by graph state.
"""

from .driver import GraphUnavailable, get_driver, graph_enabled
from .schema import ensure_graph_schema
from .sync import run_sync

__all__ = ["GraphUnavailable", "graph_enabled", "get_driver", "ensure_graph_schema", "run_sync"]
