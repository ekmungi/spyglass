"""Tests for the pure-numpy clustering core.

These functions take normalized (unit-L2) vectors so cosine == dot product; they carry no DB
or index coupling, mirroring how relevance_model stays a pure matrix-only unit.
"""

import numpy as np

from spyglass_service.cluster import cluster_cosine


def _normalize_rows(rows: list[list[float]]) -> np.ndarray:
    """Stack rows into a float32 matrix with each row scaled to unit L2 norm."""
    m = np.array(rows, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms > 0, norms, 1.0)


# --- cluster_cosine --------------------------------------------------------------------------


def test_cluster_cosine_finds_two_dense_groups() -> None:
    """Two tight groups of 3 emerge as two clusters; each carries its own member indices."""
    matrix = _normalize_rows(
        [
            [1, 0, 0, 0], [0.999, 0.02, 0, 0], [0.998, 0.03, 0, 0],  # group A -> 0,1,2
            [0, 1, 0, 0], [0.02, 0.999, 0, 0], [0.03, 0.998, 0, 0],  # group B -> 3,4,5
        ]
    )
    clusters = cluster_cosine(matrix, threshold=0.9, min_size=3)
    members = sorted(sorted(c) for c in clusters)
    assert members == [[0, 1, 2], [3, 4, 5]]


def test_cluster_cosine_excludes_groups_below_min_size() -> None:
    """A lone noise point (no dense neighbourhood) forms no cluster -- it stays Unsorted."""
    matrix = _normalize_rows(
        [
            [1, 0, 0, 0], [0.999, 0.02, 0, 0], [0.998, 0.03, 0, 0],  # dense trio
            [0, 0, 1, 0],  # noise, orthogonal to the trio
        ]
    )
    clusters = cluster_cosine(matrix, threshold=0.9, min_size=3)
    assert [sorted(c) for c in clusters] == [[0, 1, 2]]


def test_cluster_cosine_all_dissimilar_returns_no_clusters() -> None:
    """When nothing clusters, propose nothing (the 'new category only when a real cluster forms')."""
    matrix = _normalize_rows([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]])
    assert cluster_cosine(matrix, threshold=0.9, min_size=2) == []


def test_cluster_cosine_empty_matrix_returns_empty() -> None:
    """No vectors -> no clusters (no crash on the empty-Unsorted no-op path)."""
    assert cluster_cosine(np.empty((0, 4), dtype=np.float32), threshold=0.9, min_size=2) == []
