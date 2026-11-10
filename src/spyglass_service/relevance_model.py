"""Semantic-propagation relevance model.

Blends the LLM relevance prior with a semantic k-NN vote from the user's thumbed
articles:

    blended = clamp(prior + BOOST * knn_term),   knn_term in [-1, 1]

Positive labels (thumb-up) lift semantically-close items; negative labels (thumb-down) sink
them. Only genuinely-close neighbours count (cosine >= SIM_THRESHOLD), each weighted by a
distance decay and a recency decay, so:

- with no nearby labels the vote is 0 and the score is EXACTLY the prior (graceful degradation);
- one close positive always lifts, one close negative always sinks (the up/down asymmetry lives
  in how thumbs are pinned upstream, not here);
- far items are untouched (no runaway recolouring).

Propagation runs over embedding cosine ONLY -- never tags, never the LLM summary/category.
These functions are pure and matrix-free at the item level; the DB/index adapter
that gathers vectors and priors lives in relevance_serve.py.
"""

from dataclasses import dataclass

import numpy as np

from spyglass_service.enrich_prompt import bucket_from_score

# --- Tuned constants (this module is their single source of truth) ---
# Max points a fully-saturated neighbourhood can move the LLM prior. Chosen so one strong
# signal shifts a card by roughly one-and-a-half buckets (bucket width ~30) -- decisive but
# not obliterating the prior.
BOOST = 40.0
# arctic-embed-s cosine below this is "not a semantic neighbour". Empirically ~0.6 separates
# on-topic neighbours from loosely-related items for this model; below it, no propagation.
SIM_THRESHOLD = 0.6
# Cap on how many neighbours vote per item -- the closest dominate; a long tail cannot swamp.
K = 10
# Recency half-life (days): a thumb's influence halves every HALF_LIFE_DAYS, so stale opinions
# yield to fresh ones when labels conflict.
HALF_LIFE_DAYS = 30.0

# Representative 0-100 score for each bucket, used as the prior when a card has a level label
# but no numeric relevance_score (e.g. judged via the legacy apply_relevance path). Each value
# buckets back to its own level via bucket_from_score.
_LEVEL_SCORE = {"high": 85, "medium": 55, "low": 27, "out": 7}


@dataclass(frozen=True)
class Label:
    """One explicit relevance signal from the user: a thumbed item and its polarity.

    item_id: the labelled Item.id (the join key with the embedding index).
    polarity: +1.0 for thumb-up, -1.0 for thumb-down.
    age_days: days since the thumb was set, for recency weighting (0.0 = just now).
    """

    item_id: int
    polarity: float
    age_days: float = 0.0


def score_of_level(level: str | None) -> float:
    """Representative 0-100 prior for a bucket label; 50.0 (neutral) for None/unknown.

    Args:
        level: A relevance bucket ("high"/"medium"/"low"/"out") or None.

    Returns:
        A float score that buckets back to `level` (or 50.0 when there is no level).
    """
    return float(_LEVEL_SCORE.get(level or "", 50))


def knn_term(
    sims: np.ndarray,
    polarities: np.ndarray,
    ages_days: np.ndarray,
    *,
    sim_threshold: float = SIM_THRESHOLD,
    k: int = K,
    half_life_days: float = HALF_LIFE_DAYS,
) -> float:
    """Signed semantic vote in [-1, 1] from a set of labels to one item.

    Only labels with cosine >= sim_threshold count. Each contributes
    ``recency * decay * polarity`` where ``decay = (sim - t) / (1 - t)`` in [0, 1] (0 at the
    threshold, 1 at identical) and ``recency = 0.5 ** (age / half_life)``. The k
    strongest-magnitude contributions are summed and clamped to [-1, 1].

    Args:
        sims: Cosine similarities of the query item to each label (same order as the rest).
        polarities: +1/-1 per label.
        ages_days: Days since each label was set.
        sim_threshold: Minimum cosine to count as a neighbour.
        k: Max neighbours that vote (closest by magnitude).
        half_life_days: Recency half-life in days.

    Returns:
        The signed vote in [-1, 1]; 0.0 when no label is close enough.
    """
    if sims.size == 0:
        return 0.0
    mask = sims >= sim_threshold
    if not mask.any():
        return 0.0
    s = sims[mask]
    pol = polarities[mask]
    age = ages_days[mask]
    # Distance decay: 0 at the threshold, 1 at identical. Guard the degenerate ceiling case
    # (threshold == 1.0) -- there the only qualifying neighbours are exact matches (sim == 1),
    # which count at full weight, and the naive formula would divide by zero (NaN).
    span = 1.0 - sim_threshold
    if span <= 0:
        decay = np.ones_like(s)
    else:
        decay = np.clip((s - sim_threshold) / span, 0.0, 1.0)
    recency = np.power(0.5, age / half_life_days)
    contrib = recency * decay * pol
    # Keep only the k strongest contributions so a long tail of weak neighbours cannot swamp.
    if contrib.size > k:
        idx = np.argsort(-np.abs(contrib))[:k]
        contrib = contrib[idx]
    return float(np.clip(contrib.sum(), -1.0, 1.0))


def blend(prior: float, knn: float, *, boost: float = BOOST) -> float:
    """Additive nudge: ``prior + boost * knn``, clamped to [0, 100].

    Args:
        prior: The LLM relevance prior (0-100).
        knn: The signed semantic vote in [-1, 1] from ``knn_term``.
        boost: Max points a saturated vote moves the prior.

    Returns:
        The blended score in [0, 100]; exactly ``prior`` when ``knn`` is 0.
    """
    return float(np.clip(prior + boost * knn, 0.0, 100.0))


def effective_level(
    *,
    override_level: str | None,
    truly_unjudged: bool,
    prior_score: float,
    knn: float,
) -> str | None:
    """Resolve a card's displayed relevance level in priority order.

    Priority: an explicit user label wins on its own item; else a card that was never scored
    and never thumbed is unjudged (None); else the blended (prior + boosted vote) score,
    bucketed.

    Args:
        override_level: The card's explicit label (card.relevance) when relevance_override is
            set, else None.
        truly_unjudged: True when the card has no signal at all (never LLM-scored, never thumbed).
        prior_score: The numeric LLM prior (or a level-mapped fallback), 0-100.
        knn: The signed semantic vote in [-1, 1].

    Returns:
        A bucket level, or None for an unjudged card.
    """
    if override_level is not None:
        return override_level
    if truly_unjudged:
        return None
    return bucket_from_score(round(blend(prior_score, knn)))
