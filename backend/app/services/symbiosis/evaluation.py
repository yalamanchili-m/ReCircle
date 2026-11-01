"""Curated synthetic evaluation for symbiosis algorithms (blueprint gate).

A known graph with hand-checkable structure: BFS paths, PageRank ranking,
and Louvain clusters must be reproducible and documented here. This verifies
the algorithms, not real-world data quality (explicitly disclaimed).
"""

from app.services.symbiosis import algorithms
from app.services.symbiosis.graph import SymbiosisGraph

EVALUATION_VERSION = "symbiosis-eval-v1"


def _known_graph() -> SymbiosisGraph:
    """Small hand-checkable graph:

    producer_org --OWNS-- listing_a --MATERIAL-- copper --INDUSTRY-- cable_industry
                                                             |
    consumer_org --SEEKS-- req_b -------MATERIAL-------------+

    The shortest producer->consumer path is producer-org -> listing_a ->
    copper -> req_b -> consumer-org (depth 4).
    """
    graph = SymbiosisGraph()
    graph.add_node("org:p1", ["Organization"], {"name": "Producer One"})
    graph.add_node("org:c1", ["Organization"], {"name": "Consumer One"})
    graph.add_node("org:far", ["Organization"], {"name": "Unrelated Org"})
    graph.add_node("listing:l1", ["Listing"], {"title": "Copper wire scrap"})
    graph.add_node("requirement:r1", ["Requirement"], {"title": "Copper needed"})
    graph.add_node("material:metals.copper", ["MaterialType"], {"label": "Copper scrap"})
    graph.add_node("industry:cable", ["Industry"], {"name": "Cable industry"})
    graph.add_node("application:cables", ["Application"], {"name": "Cable making"})

    graph.add_edge("org:p1", "listing:l1", "OWNS", {"is_fact": True})
    graph.add_edge("listing:l1", "material:metals.copper", "HAS_MATERIAL_TYPE", {})
    graph.add_edge("org:c1", "requirement:r1", "SEEKS", {"is_fact": True})
    graph.add_edge("requirement:r1", "material:metals.copper", "WANTS_MATERIAL_TYPE", {})
    graph.add_edge("material:metals.copper", "industry:cable", "SUITED_INDUSTRY", {})
    graph.add_edge("material:metals.copper", "application:cables", "SUITABLE_FOR", {})
    return graph


def evaluate_symbiosis() -> dict:
    graph = _known_graph()

    # --- BFS: known shortest path, reproducible across calls --------------
    paths_1 = algorithms.bfs_shortest_paths(graph, "org:p1", "org:c1", max_depth=4)
    paths_2 = algorithms.bfs_shortest_paths(graph, "org:p1", "org:c1", max_depth=4)
    assert paths_1 == paths_2, "BFS must be deterministic"
    expected_path = [
        "org:p1", "listing:l1", "material:metals.copper", "requirement:r1", "org:c1"
    ]
    bfs_case = {
        "name": "known_shortest_path",
        "source": "org:p1",
        "target": "org:c1",
        "max_depth": 4,
        "expected_path": expected_path,
        "actual_paths": paths_1,
        "passed": paths_1[:1] == [expected_path],
        "detail": "Shortest producer→consumer path runs through the shared copper material node",
    }
    bfs_bounded_case = {
        "name": "bounded_depth_excludes_path",
        "source": "org:p1",
        "target": "org:far",
        "max_depth": 2,
        "expected_path": [],
        "actual_paths": algorithms.bfs_shortest_paths(graph, "org:p1", "org:far", max_depth=2),
        "passed": algorithms.bfs_shortest_paths(graph, "org:p1", "org:far", max_depth=2) == [],
        "detail": "org:far is connected only through the industry node at depth 5; "
        "a depth-2 bound correctly excludes it",
    }

    # --- PageRank: the shared material node must dominate ------------------
    pagerank_1 = algorithms.pagerank(graph)
    pagerank_2 = algorithms.pagerank(graph)
    assert pagerank_1 == pagerank_2, "PageRank must be deterministic"
    top = max(pagerank_1, key=lambda node: (pagerank_1[node], node))
    pagerank_case = {
        "name": "hub_material_dominates",
        "expected_top": "material:metals.copper",
        "actual_top": top,
        "scores": {node: round(score, 8) for node, score in sorted(pagerank_1.items())},
        "passed": top == "material:metals.copper",
        "detail": "The copper node carries the most structural weight: both the "
        "producer and consumer sides connect through it",
    }

    # --- Louvain: the copper loop forms one community -----------------------
    communities_1 = algorithms.louvain_communities(graph)
    communities_2 = algorithms.louvain_communities(graph)
    assert communities_1 == communities_2, "Louvain must be deterministic"
    cluster_case = {
        "name": "copper_loop_clusters_together",
        "expected_same_cluster": [
            ["org:p1", "listing:l1", "material:metals.copper", "requirement:r1", "org:c1"]
        ],
        "actual_communities": communities_1,
        "passed": len(
            {communities_1[node] for node in
             ("org:p1", "listing:l1", "material:metals.copper", "requirement:r1", "org:c1")}
        ) == 1,
        "detail": "All nodes on the producer→consumer copper loop fall in one community",
    }
    isolated_case = {
        "name": "isolated_org_is_separate",
        "passed": communities_1["org:far"] != communities_1["material:metals.copper"],
        "detail": "The unrelated org (no edges) is not merged into the copper cluster",
    }

    cases = [bfs_case, bfs_bounded_case, pagerank_case, cluster_case, isolated_case]
    return {
        "evaluation_version": EVALUATION_VERSION,
        "dataset": "synthetic known graph (5 checks); verifies algorithm determinism "
        "and hand-checked structure only — not real data quality",
        "passed": sum(1 for case in cases if case["passed"]),
        "total": len(cases),
        "cases": cases,
        "disclaimer": "Synthetic verification set. Real-world symbiosis quality "
        "depends on validated data; precision/recall on real data is explicitly "
        "unavailable (no labeled dataset).",
    }
