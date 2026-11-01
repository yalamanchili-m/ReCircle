"""Pure-Python graph algorithms for symbiosis discovery.

Deterministic by construction: nodes are processed in sorted order and ties
are broken by id/label, so identical graphs always produce identical outputs
(blueprint Phase 7 acceptance gate). No external dependencies.
"""

from collections import deque

from app.services.symbiosis.graph import SymbiosisGraph


def bfs_from_source(
    graph: SymbiosisGraph,
    source_id: str,
    max_depth: int = 4,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Single-source bounded BFS.

    Returns (depth, parents): depth maps reachable node -> hop count,
    parents maps node -> list of predecessors on tied shortest paths.
    Deterministic (neighbours expanded in sorted order).
    """
    if source_id not in graph.nodes:
        return {}, {}
    depth: dict[str, int] = {source_id: 0}
    parents: dict[str, list[str]] = {source_id: []}
    frontier = deque([source_id])
    while frontier:
        current = frontier.popleft()
        if depth[current] >= max_depth:
            continue
        for neighbor in sorted(graph.adjacency.get(current, {})):
            if neighbor not in depth:
                depth[neighbor] = depth[current] + 1
                parents[neighbor] = [current]
                frontier.append(neighbor)
            elif depth[neighbor] == depth[current] + 1:
                parents[neighbor].append(current)
    return depth, parents


def reconstruct_path(
    source_id: str,
    target_id: str,
    depth: dict[str, int],
    parents: dict[str, list[str]],
    max_paths: int = 5,
) -> list[list[str]]:
    """Reconstruct tied shortest paths from a bfs_from_source result."""
    if target_id == source_id:
        return [[source_id]]
    if target_id not in depth:
        return []
    paths: list[list[str]] = []

    def build(node_id: str, acc: list[str]) -> None:
        if len(paths) >= max_paths:
            return
        if node_id == source_id:
            paths.append([source_id, *acc])
            return
        for parent in sorted(parents[node_id]):
            build(parent, [node_id, *acc])

    build(target_id, [])
    return paths


def bfs_shortest_paths(
    graph: SymbiosisGraph,
    source_id: str,
    target_id: str,
    max_depth: int = 4,
    max_paths: int = 5,
) -> list[list[str]]:
    """All tied shortest paths from source to target, bounded by max_depth.

    Returns a list of node-id paths (inclusive of both endpoints). Empty when
    no path exists within the bound. Neighbours are expanded in sorted order,
    making the output deterministic.
    """
    if source_id not in graph.nodes or target_id not in graph.nodes:
        return []
    if source_id == target_id:
        return [[source_id]]

    depth, parents = bfs_from_source(graph, source_id, max_depth)
    return reconstruct_path(source_id, target_id, depth, parents, max_paths)


def pagerank(
    graph: SymbiosisGraph,
    damping: float = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-10,
) -> dict[str, float]:
    """Degree-normalized PageRank on the undirected graph (deterministic)."""
    node_ids = sorted(graph.nodes)
    n = len(node_ids)
    if n == 0:
        return {}
    scores = {node_id: 1.0 / n for node_id in node_ids}
    for _ in range(max_iterations):
        new_scores = {}
        dangling_mass = sum(scores[node_id] for node_id in node_ids if not graph.adjacency.get(node_id))
        for node_id in node_ids:
            neighbors = graph.adjacency.get(node_id, {})
            incoming = sum(
                scores[neighbor] * weight / sum(graph.adjacency[neighbor].values())
                for neighbor, weight in neighbors.items()
            )
            new_scores[node_id] = (1.0 - damping) / n + damping * incoming + damping * dangling_mass / n
        delta = sum(abs(new_scores[node_id] - scores[node_id]) for node_id in node_ids)
        scores = new_scores
        if delta < tolerance:
            break
    return scores


def louvain_communities(
    graph: SymbiosisGraph,
    resolution: float = 1.0,
    max_levels: int = 6,
) -> dict[str, int]:
    """Deterministic Louvain community detection on the undirected graph.

    Returns a mapping of node id -> community id. Nodes are visited in sorted
    order and ties are broken toward the smallest community label, so the same
    graph always yields the same partition.
    """
    node_ids = sorted(graph.nodes)
    if not node_ids:
        return {}

    # Relabel to dense integers; adjacency as dicts of index -> weight.
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    adjacency = [dict() for _ in node_ids]
    for node_id, neighbors in graph.adjacency.items():
        for neighbor, weight in neighbors.items():
            adjacency[index[node_id]][index[neighbor]] = weight

    degrees = [sum(neighbors.values()) for neighbors in adjacency]
    total_weight = sum(degrees) / 2.0
    if total_weight == 0:
        return {node_id: 0 for node_id in node_ids}

    membership = list(range(len(node_ids)))  # current node -> community
    community_weights = list(degrees)  # sum of degrees per community
    node_to_community = list(range(len(node_ids)))  # aggregated node -> community

    def local_pass(adj, deg, communities, com_weights, m):
        moved = 0
        for node in sorted(range(len(adj))):
            neighbors = adj[node]
            node_degree = deg[node]
            current = communities[node]
            # Detach node from its community.
            com_weights[current] -= node_degree
            links: dict[int, float] = {}
            for neighbor, weight in neighbors.items():
                com = communities[neighbor]
                links[com] = links.get(com, 0.0) + weight
            best_com = current
            best_gain = 0.0
            for com in sorted(links):
                gain = links[com] - resolution * com_weights[com] * node_degree / (2.0 * m)
                if gain > best_gain + 1e-12:
                    best_gain = gain
                    best_com = com
            communities[node] = best_com
            if best_com >= len(com_weights):
                com_weights.extend([0.0] * (best_com + 1 - len(com_weights)))
            com_weights[best_com] += node_degree
            if best_com != current:
                moved += 1
        return moved

    # Level 1: direct communities over original nodes.
    level_membership = membership[:]
    level_adj = adjacency
    level_deg = degrees
    level_com_weights = community_weights[:]
    m = total_weight

    for _level in range(max_levels):
        communities = level_membership[:]
        moved = local_pass(level_adj, level_deg, communities, level_com_weights, m)
        level_membership = communities
        if moved == 0:
            break
        # Map original nodes through the aggregation (compose the chain).
        communities_sorted = sorted(set(communities))
        remap = {com: i for i, com in enumerate(communities_sorted)}
        node_to_community = [
            remap[communities[node_to_community[node]]] for node in range(len(node_ids))
        ]
        # Aggregate the graph by community.
        new_size = len(communities_sorted)
        new_adj = [dict() for _ in range(new_size)]
        for node, neighbors in enumerate(level_adj):
            for neighbor, weight in neighbors.items():
                c1 = remap[communities[node]]
                c2 = remap[communities[neighbor]]
                if c1 == c2:
                    continue
                new_adj[c1][c2] = new_adj[c1].get(c2, 0.0) + weight
        new_deg = [sum(neighbors.values()) for neighbors in new_adj]
        m_new = sum(new_deg) / 2.0
        if m_new == 0:
            break
        level_adj = new_adj
        level_deg = new_deg
        level_com_weights = new_deg[:]
        m = m_new
        # Fresh labels for the aggregated graph.
        level_membership = list(range(new_size))

    return {
        node_ids[node]: node_to_community[node]
        for node in range(len(node_ids))
    }
