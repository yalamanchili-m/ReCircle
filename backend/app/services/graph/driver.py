"""Neo4j driver management.

The driver is created lazily and cached. Any connectivity problem surfaces as
`GraphUnavailable` so callers can degrade gracefully instead of leaking
driver exceptions into API responses.
"""

import logging
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger("app.graph")


class GraphUnavailable(Exception):
    """Raised when the graph database is disabled or unreachable."""


@lru_cache(maxsize=1)
def _cached_driver():
    from neo4j import GraphDatabase

    settings = get_settings()
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=3.0,
        )
        driver.verify_connectivity()
        return driver
    except Exception as exc:
        logger.info("Neo4j unavailable: %s", exc)
        return None


def get_driver():
    """Return a verified driver or None when Neo4j is disabled/unreachable."""
    settings = get_settings()
    if not settings.neo4j_enabled:
        return None
    return _cached_driver()


def graph_enabled() -> bool:
    settings = get_settings()
    return settings.neo4j_enabled and get_driver() is not None


def require_driver():
    driver = get_driver()
    if driver is None:
        raise GraphUnavailable("Neo4j is disabled or unreachable")
    return driver


def reset_driver_cache() -> None:
    _cached_driver.cache_clear()
