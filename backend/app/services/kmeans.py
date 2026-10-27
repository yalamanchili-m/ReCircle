"""Deterministic K-means (blueprint Phase 11).

Pure Python, no dependencies, fully deterministic:
- farthest-first traversal initialization (no random seed required at all),
- Lloyd iterations with a fixed iteration cap and convergence tolerance,
- empty-cluster restart by reassigning the farthest point.

The clustering is EXPLORATORY ONLY: results are not authoritative material
classes, quality grades, or safety predictions, and every response carries
that disclaimer.
"""

RESULT_VERSION = "kmeans-v1"

MAX_ITERATIONS = 100
TOLERANCE = 1e-9


class KMeansError(ValueError):
    """Invalid clustering configuration or inputs."""


def centroids_equal(a: list[float], b: list[float], tolerance: float) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def deterministic_kmeans(
    points: list[list[float]],
    k: int,
    max_iterations: int = MAX_ITERATIONS,
) -> dict:
    """Run deterministic K-means on prepared numeric vectors.

    Returns {"assignments", "centroids", "inertia", "iterations"}.
    Raises KMeansError when k or the inputs are invalid.
    """
    if k < 2 or k > 12:
        raise KMeansError(f"k must be within [2, 12], got {k}")
    n = len(points)
    if n < k:
        raise KMeansError(
            f"sample size {n} is smaller than k={k}; not enough data"
        )

    centers = _farthest_first_initialization(points, k)
    assignments = [-1] * n
    iterations = 0

    for _ in range(max_iterations):
        iterations += 1
        changed = False
        total = 0.0
        for i, point in enumerate(points):
            center, distance = _nearest_center(point, centers)
            total += distance
            if assignments[i] != center:
                assignments[i] = center
                changed = True
        new_centers = _recompute_centers(points, assignments, centers)
        stable = all(
            centroids_equal(centers[c], new_centers[c], TOLERANCE)
            for c in range(k)
        )
        centers = new_centers
        if stable and not changed:
            break

    inertia = sum(
        _sq_distance(points[i], centers[assignments[i]]) for i in range(n)
    )
    return {
        "assignments": assignments,
        "centroids": centers,
        "inertia": round(inertia, 6),
        "iterations": iterations,
    }


def _sq_distance(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _nearest_center(
    point: list[float], centers: list[list[float]]
) -> tuple[int, float]:
    best = 0
    best_distance = float("inf")
    for index, center in enumerate(centers):
        distance = _sq_distance(point, center)
        # Strict '<' keeps the FIRST center on ties: deterministic.
        if distance < best_distance:
            best = index
            best_distance = distance
    return best, best_distance


def _farthest_first_initialization(
    points: list[list[float]], k: int
) -> list[list[float]]:
    """Gonzalez-style deterministic init.

    First center: the point closest to the overall mean (most typical).
    Each subsequent center: the point farthest from ALL chosen centers so
    far (tie-break by input order via strict '>').
    """
    dimensions = len(points[0])
    mean = [sum(p[d] for p in points) / len(points) for d in range(dimensions)]
    first = min(
        range(len(points)),
        key=lambda i: (_sq_distance(points[i], mean), i),
    )
    chosen = [points[first]]
    min_distances = [None] * len(points)

    while len(chosen) < k:
        selected, best = None, -1.0
        for i, point in enumerate(points):
            distance_to_latest = _sq_distance(point, chosen[-1])
            if min_distances[i] is None or distance_to_latest < min_distances[i]:
                min_distances[i] = distance_to_latest
            # strict '>' keeps the earliest index on ties
            if min_distances[i] > best:
                best = min_distances[i]
                selected = i
        if selected is None:  # pragma: no cover - guarded by n >= k
            raise KMeansError("Could not pick another distinct center")
        chosen.append(points[selected])
    return chosen


def _recompute_centers(
    points: list[list[float]],
    assignments: list[int],
    previous: list[list[float]],
) -> list[list[float]]:
    dimensions = len(previous[0])
    centers: list[list[float]] = []
    for cluster in range(len(previous)):
        members = [
            points[i] for i, assigned in enumerate(assignments) if assigned == cluster
        ]
        if members:
            centers.append(
                [
                    round(sum(p[d] for p in members) / len(members), 10)
                    for d in range(dimensions)
                ]
            )
        else:
            # Empty cluster: keep the previous center but nudge it to the
            # currently farthest point so the next pass attracts members.
            farthest, best = 0, -1.0
            for i, point in enumerate(points):
                distance = _sq_distance(point, previous[cluster])
                if distance > best:
                    best = distance
                    farthest = i
            centers.append(list(points[farthest]))
    return centers


def silhouette_reduction(points: list[list[float]], assignments: list[int]) -> float:
    """Mean silhouette coefficient (O(n^2); capped by the caller)."""
    n = len(points)
    if n < 3 or len(set(assignments)) < 2:
        return 0.0
    clusters: dict[int, list[int]] = {}
    for index, cluster in enumerate(assignments):
        clusters.setdefault(cluster, []).append(index)

    total = 0.0
    for index in range(n):
        own = clusters[assignments[index]]
        if len(own) == 1:
            total += 0.0
            continue
        a = sum(
            _sq_distance(points[index], points[other])
            for other in own
            if other != index
        ) / (len(own) - 1)
        b = min(
            sum(_sq_distance(points[index], points[other]) for other in members)
            / len(members)
            for cluster, members in clusters.items()
            if cluster != assignments[index] and members
        )
        total += (b - a) / max(a, b)
    return round(total / n, 4)
