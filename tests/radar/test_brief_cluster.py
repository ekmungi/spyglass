"""Tests for grouping candidate items into stories."""

from datetime import datetime, timedelta

import numpy as np

from spyglass_service.radar.brief.cluster import Candidate, cluster_candidates

T0 = datetime(2026, 11, 10, 9, 0)


def cand(item_id: int, score: int = 60, hours: float = 0, **kw) -> Candidate:
    """A candidate published `hours` after T0."""
    return Candidate(item_id=item_id, score=score, when=T0 + timedelta(hours=hours), **kw)


def vecs(rows: dict[int, list[float]]) -> tuple[list[int], np.ndarray]:
    """Normalised vectors in the shape EmbeddingIndex.matrix_for returns."""
    ids = list(rows)
    m = np.array([rows[i] for i in ids], dtype=np.float32)
    return ids, m / np.linalg.norm(m, axis=1, keepdims=True)


def ids_of(stories) -> list[list[int]]:
    """Member item ids of each story, lead first."""
    return [[m.item_id for m in s.members] for s in stories]


def test_same_event_key_groups_and_lead_is_highest_score() -> None:
    stories = cluster_candidates(
        [cand(1, 50, event_key="x"), cand(2, 80, event_key="x"), cand(3, 70, event_key="y")]
    )
    assert ids_of(stories) == [[2, 1], [3]]


def test_empty_event_key_never_groups() -> None:
    stories = cluster_candidates([cand(1, event_key=""), cand(2, event_key=""), cand(3), cand(4)])
    assert len(stories) == 4


def test_similar_vectors_group_and_dissimilar_do_not() -> None:
    v = vecs({1: [1, 0, 0], 2: [0.99, 0.05, 0], 3: [0, 1, 0]})
    stories = cluster_candidates([cand(1), cand(2), cand(3)], v)
    assert sorted(sorted(g) for g in ids_of(stories)) == [[1, 2], [3]]


def test_threshold_is_inclusive_boundary() -> None:
    v = vecs({1: [1, 0], 2: [0.8, 0.6]})  # cosine exactly 0.8
    assert len(cluster_candidates([cand(1), cand(2)], v, threshold=0.8001)) == 2
    assert len(cluster_candidates([cand(1), cand(2)], v, threshold=0.79)) == 1


def test_items_more_than_four_days_apart_never_group() -> None:
    v = vecs({1: [1, 0], 2: [1, 0]})
    stories = cluster_candidates([cand(1, event_key="k"), cand(2, hours=24 * 5, event_key="k")], v)
    assert len(stories) == 2


def test_grouping_does_not_chain_unrelated_items() -> None:
    """1~2 and 2~3 are 0.866 alike, 1 and 3 only 0.5: 3 is compared with the story's lead (1),
    so it is not pulled into the story through 2."""
    v = vecs({1: [1, 0], 2: [0.866, 0.5], 3: [0.5, 0.866]})
    stories = cluster_candidates([cand(1), cand(2), cand(3)], v, threshold=0.86)
    assert ids_of(stories) == [[1, 2], [3]]


def test_the_reviewers_chain_is_broken() -> None:
    """The reviewer's case: b halfway between a and c."""
    a, c = np.array([1.0, 0, 0, 0]), np.array([0.5, 0.866, 0, 0])
    b = (a + c) / np.linalg.norm(a + c)
    v = vecs({1: list(a), 2: list(b), 3: list(c)})
    stories = cluster_candidates([cand(1), cand(2), cand(3)], v)
    assert ids_of(stories) == [[1, 2], [3]]


def test_a_shared_event_key_needs_some_similarity_when_both_have_vectors() -> None:
    """A sloppy event key cannot merge two unrelated stories."""
    unrelated = vecs({1: [1, 0], 2: [0.5, 0.866]})  # cosine 0.5
    related = vecs({1: [1, 0], 2: [0.6, 0.8]})      # cosine 0.6
    keyed = [cand(1, event_key="ai-news"), cand(2, event_key="ai-news")]
    assert len(cluster_candidates(keyed, unrelated)) == 2
    assert len(cluster_candidates(keyed, related)) == 1


def test_the_same_article_stored_twice_is_one_source() -> None:
    """Two items with the same normalised address are one story and one source."""
    stories = cluster_candidates([
        cand(1, 70, url="https://www.example.com/story/?utm_source=x", publication="Example"),
        cand(2, 60, url="http://example.com/story", publication="example.com"),
    ])
    assert ids_of(stories) == [[1, 2]] and stories[0].publications == 1


def test_tie_on_score_breaks_to_earliest_publication() -> None:
    stories = cluster_candidates([cand(1, 70, hours=5, event_key="k"), cand(2, 70, hours=1, event_key="k")])
    assert stories[0].lead.item_id == 2


def test_items_without_vectors_still_group_by_key_and_missing_vectors_are_safe() -> None:
    v = vecs({1: [1, 0]})
    stories = cluster_candidates([cand(1, event_key="k"), cand(2, event_key="k"), cand(3)], v)
    assert sorted(len(s.members) for s in stories) == [1, 2]


def test_empty_input_and_empty_vectors() -> None:
    assert cluster_candidates([]) == []
    assert len(cluster_candidates([cand(1)], ([], np.empty((0, 3), dtype=np.float32)))) == 1


def test_publications_counts_distinct_names_case_insensitively() -> None:
    story = cluster_candidates(
        [cand(1, event_key="k", publication="STAT"), cand(2, event_key="k", publication="stat"),
         cand(3, event_key="k", publication="Reuters")]
    )[0]
    assert story.publications == 2
