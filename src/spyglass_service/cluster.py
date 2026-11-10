"""Pure-numpy clustering core for the Recategorize pass.

Dependency-free by design (numpy rather than scikit-learn/HDBSCAN, to keep the desktop
install lean). Inputs are the index's already-normalized arctic vectors, so cosine similarity is
a single matmul (M @ M.T). No DB or EmbeddingIndex coupling -- this stays a matrix-only unit,
mirroring relevance_model.
"""

import numpy as np


def cluster_cosine(
    matrix: np.ndarray, *, threshold: float, min_size: int
) -> list[list[int]]:
    """Density-seeded cosine-threshold clustering; returns groups of row indices.

    Discovers candidate new categories in the Unsorted pile: a cluster forms only around a
    genuinely dense region (a new category only when the embeddings genuinely
    cluster). Each round seeds on the still-unassigned point with the most above-threshold
    neighbours, claims that neighbourhood as a cluster, and repeats until the densest remaining
    region is smaller than min_size. Deterministic (argmax ties break to the lowest index).

    Args:
        matrix: (n, dim) normalized vectors.
        threshold: Minimum cosine for two points to be neighbours.
        min_size: Smallest neighbourhood that may become a cluster; sparser regions stay Unsorted.

    Returns:
        A list of clusters, each a list of row indices, in discovery order (densest first).
        Empty when there are no vectors or nothing reaches min_size.
    """
    n = int(matrix.shape[0])
    if n == 0:
        return []
    # Boolean adjacency over the whole set: neighbours[i, j] is True when cos(i, j) >= threshold.
    # The diagonal is a point's self-similarity (~1.0 for unit vectors), so for any threshold well
    # below 1 -- as the callers use -- a point is its own neighbour and counts toward its density.
    neighbours = (matrix @ matrix.T) >= threshold
    assigned = np.zeros(n, dtype=bool)
    clusters: list[list[int]] = []
    while not assigned.all():
        available = ~assigned
        # Neighbour count among still-available points, zeroed for already-assigned rows so a
        # densest-seed argmax never lands on one already placed.
        degree = (neighbours & available[None, :]).sum(axis=1) * available
        seed = int(degree.argmax())
        if degree[seed] < min_size:
            break  # densest remaining region too sparse -> the rest stays Unsorted
        members = np.where(neighbours[seed] & available)[0]
        assigned[members] = True
        clusters.append([int(i) for i in members])
    return clusters
