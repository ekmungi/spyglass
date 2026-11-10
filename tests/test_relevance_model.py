"""Tests for the semantic-propagation relevance model.

The core is a pure additive nudge: blended = clamp(prior + BOOST * knn_term), where knn_term
is a signed cosine-weighted vote in [-1, 1] from the user's thumbed articles. Positive labels
lift semantic neighbours, negatives sink them, and far items (cosine below the threshold)
contribute nothing -- so with no nearby labels the score is exactly the prior.
"""

import numpy as np

from spyglass_service.relevance_model import (
    SIM_THRESHOLD,
    blend,
    effective_level,
    knn_term,
    score_of_level,
)


def test_one_positive_label_lifts_a_near_neighbour() -> None:
    """A close positive neighbour (cosine well above threshold) pushes the score above the prior."""
    term = knn_term(np.array([0.9]), np.array([1.0]), np.array([0.0]))
    assert term > 0
    assert blend(50.0, term) > 50.0


def test_one_negative_label_sinks_a_near_neighbour() -> None:
    """A close negative neighbour pulls the score below the prior."""
    term = knn_term(np.array([0.9]), np.array([-1.0]), np.array([0.0]))
    assert term < 0
    assert blend(50.0, term) < 50.0


def test_far_labels_do_not_move_the_score() -> None:
    """A distant label (cosine below the threshold) contributes nothing: score == prior."""
    term = knn_term(np.array([0.3]), np.array([1.0]), np.array([0.0]))
    assert term == 0.0
    assert blend(50.0, term) == 50.0


def test_no_labels_leaves_the_prior_untouched() -> None:
    """With an empty label pool the blended score is exactly the LLM prior (graceful degrade)."""
    empty = np.array([])
    term = knn_term(empty, empty, empty)
    assert term == 0.0
    assert blend(72.0, term) == 72.0


def test_recency_weight_reduces_an_old_labels_influence() -> None:
    """An older thumb lifts a neighbour less than a fresh one (recency decay)."""
    fresh = knn_term(np.array([0.9]), np.array([1.0]), np.array([0.0]))
    old = knn_term(np.array([0.9]), np.array([1.0]), np.array([60.0]))  # 2 half-lives
    assert 0 < old < fresh


def test_many_close_positives_saturate_and_clamp() -> None:
    """Several strong positive neighbours saturate the vote at +1 and clamp the score at 100."""
    sims = np.array([0.95, 0.95, 0.95, 0.95])
    pol = np.array([1.0, 1.0, 1.0, 1.0])
    ages = np.zeros(4)
    assert knn_term(sims, pol, ages) == 1.0
    assert blend(90.0, knn_term(sims, pol, ages)) == 100.0


def test_only_the_k_strongest_neighbours_vote() -> None:
    """With more labels than k, only the k strongest-magnitude contributions count."""
    sims = np.array([0.95, 0.65])  # one strong positive, one weak (near-threshold) negative
    pol = np.array([1.0, -1.0])
    ages = np.zeros(2)
    capped = knn_term(sims, pol, ages, k=1)    # only the strong positive survives the cap
    uncapped = knn_term(sims, pol, ages, k=5)  # the weak negative also subtracts
    assert capped > uncapped
    assert capped > 0


def test_conflicting_labels_partially_cancel() -> None:
    """A near positive and an equally-near negative cancel to no net movement."""
    sims = np.array([0.9, 0.9])
    pol = np.array([1.0, -1.0])
    ages = np.zeros(2)
    assert knn_term(sims, pol, ages) == 0.0


def test_score_of_level_round_trips_through_buckets() -> None:
    """Each representative bucket score buckets back to its own level (fallback prior)."""
    from spyglass_service.enrich_prompt import bucket_from_score

    for level in ("high", "medium", "low", "out"):
        assert bucket_from_score(round(score_of_level(level))) == level
    assert score_of_level(None) == 50.0


# --- effective_level: the priority resolution (override -> unjudged -> blended) ---


def test_effective_level_override_wins() -> None:
    """An explicit user label wins outright, ignoring prior and neighbours."""
    assert effective_level(override_level="out", truly_unjudged=False, prior_score=90.0, knn=1.0) == "out"


def test_effective_level_truly_unjudged_is_none() -> None:
    """A card never scored and never thumbed resolves to None (unjudged)."""
    assert effective_level(override_level=None, truly_unjudged=True, prior_score=50.0, knn=0.0) is None


def test_effective_level_blends_prior_and_knn() -> None:
    """An unlabeled judged card buckets its blended (prior + boosted vote) score."""
    # prior 55 (medium) lifted by a saturated positive vote -> 95 -> high.
    assert effective_level(override_level=None, truly_unjudged=False, prior_score=55.0, knn=1.0) == "high"
    # prior 40 (low-medium edge) sunk by a saturated negative vote -> 0 -> out.
    assert effective_level(override_level=None, truly_unjudged=False, prior_score=40.0, knn=-1.0) == "out"


def test_knn_term_threshold_at_ceiling_does_not_nan() -> None:
    """sim_threshold == 1.0 must not divide by zero: an exact-match neighbour counts at full weight."""
    term = knn_term(np.array([1.0]), np.array([1.0]), np.array([0.0]), sim_threshold=1.0)
    assert not np.isnan(term)
    assert term == 1.0


def test_sim_threshold_is_a_sane_arctic_cosine() -> None:
    """The neighbour threshold sits in the arctic-embed cosine range (documented constant)."""
    assert 0.0 < SIM_THRESHOLD < 1.0
