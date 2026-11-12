"""Group candidate items into stories: one event appears once, with all of its sources.

Candidates are visited best first; each one either joins an existing story or starts a new one
with itself as the lead. An item joins a story only by comparison with that story's LEAD item,
never with another member, so "A matches B" and "B matches C" no longer pull an unrelated C
into A's story (grouping is not transitive). It joins when, within the time window of the lead:

- its embedding is at least SIMILARITY_THRESHOLD alike with the lead's, or
- it has exactly the lead's event key and, when both have embeddings, they are at least
  KEY_MIN_SIMILARITY alike (so a sloppy shared key cannot merge two unrelated stories), or
- it has the same normalised address as an item already in the story (the same article
  stored twice), whatever its embedding.

When several stories qualify, the one whose lead is most alike wins. Everything here is a pure
function of its inputs.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from spyglass_service.radar.brief.addresses import normalize_address

# Cosine similarity at or above which an item is treated as the same event as a story's lead.
# Vectors are normalised, so this is a dot product; 0.84 keeps rewrites of one announcement
# together without merging two different announcements about the same topic.
SIMILARITY_THRESHOLD = 0.84
# Two items with the same event key must still be at least this alike when both have vectors.
KEY_MIN_SIMILARITY = 0.6
# Items published further apart than this are never the same story, even with the same key.
TIME_WINDOW = timedelta(days=4)


@dataclass(frozen=True)
class Candidate:
    """One item that could appear in the brief, with just the fields clustering and ranking need."""

    item_id: int
    score: int
    # Publication time (or fetch time when the source gave none), naive UTC.
    when: datetime
    publication: str = ""
    event_key: str | None = None
    kind: str = "news"
    tier: str = "unjudged"
    section: str = ""
    from_user: bool = False
    # True when the item is about an active watch entity of any kind.
    watched: bool = False
    # True when it is about an active entity the brief's watch section covers (a company or a
    # regulator; see `watch.registry.WATCH_SECTION_KINDS`).
    competitor: bool = False
    # (name, category) of every active watch entity the item is about.
    watch: tuple[tuple[str, str], ...] = ()
    upvotes: int = 0
    # The item's address; two items with the same normalised address are one source.
    url: str = ""


def source_key(c: Candidate) -> str:
    """What makes a member a distinct source: its publication, else its address."""
    return c.publication.strip().lower() or normalize_address(c.url) or f"#{c.item_id}"


@dataclass(frozen=True)
class Story:
    """Items that report one event. `members[0]` is always the lead item."""

    members: tuple[Candidate, ...]

    @property
    def lead(self) -> Candidate:
        """The item the story is shown under."""
        return self.members[0]

    @property
    def distinct_members(self) -> tuple[Candidate, ...]:
        """Members with repeats of one article (same normalised address) removed, lead first."""
        seen: set[str] = set()
        kept = []
        for m in self.members:
            address = normalize_address(m.url)
            if address and address in seen:
                continue
            seen.add(address)
            kept.append(m)
        return tuple(kept)

    @property
    def publications(self) -> int:
        """How many distinct publications reported the event (unnamed ones count once each;
        the same article stored twice counts once)."""
        return len({source_key(m) for m in self.distinct_members})

    @property
    def from_user(self) -> bool:
        """True when the reader sent in any member."""
        return any(m.from_user for m in self.members)

    @property
    def watched(self) -> bool:
        """True when any member is about an active watch entity."""
        return any(m.watched for m in self.members)

    @property
    def competitor(self) -> bool:
        """True when any member is about a company or regulator on the watch register."""
        return any(m.competitor for m in self.members)

    @property
    def watch(self) -> tuple[tuple[str, str], ...]:
        """(name, category) of each watched organisation the story is about, without repeats."""
        return tuple(dict.fromkeys(pair for m in self.members for pair in m.watch))


def lead_sort_key(c: Candidate) -> tuple:
    """Order that puts the lead first: highest score, then earliest publication, then lowest id."""
    return (-c.score, c.when, c.item_id)


class _Similarity:
    """Cosine similarity between two candidates' vectors, or None when one has no vector."""

    def __init__(self, vectors: tuple[list[int], np.ndarray] | None) -> None:
        """Index the rows of `vectors` (as returned by `EmbeddingIndex.matrix_for`)."""
        self._row: dict[int, int] = {}
        self._sims = None
        if vectors is not None and len(vectors[0]) > 0:
            self._row = {item_id: r for r, item_id in enumerate(vectors[0])}
            # All pairs at once: a few thousand candidates make a matrix of a few megabytes.
            self._sims = vectors[1] @ vectors[1].T

    def __call__(self, a: Candidate, b: Candidate) -> float | None:
        """Dot product of the two normalised vectors."""
        ra, rb = self._row.get(a.item_id), self._row.get(b.item_id)
        if self._sims is None or ra is None or rb is None:
            return None
        return float(self._sims[ra, rb])


def _affinity(lead: Candidate, c: Candidate, sim: _Similarity, threshold: float) -> float | None:
    """How strongly `c` belongs with `lead` (higher is better), or None when it does not."""
    cosine = sim(lead, c)
    if lead.event_key and c.event_key == lead.event_key:
        if cosine is None:
            return 1.0
        return cosine if cosine >= KEY_MIN_SIMILARITY else None
    if cosine is not None and cosine >= threshold:
        return cosine
    return None


def cluster_candidates(
    candidates: list[Candidate],
    vectors: tuple[list[int], np.ndarray] | None = None,
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    window: timedelta = TIME_WINDOW,
) -> list[Story]:
    """Group candidates into stories (see the module docstring for the rule).

    candidates: the items to group (not modified).
    vectors: `(item_ids, matrix)` as returned by `EmbeddingIndex.matrix_for`; row i is the
        normalised vector of item_ids[i]. Items without a vector can still match by event key
        or by address.
    Returns the stories ordered by their lead's score, best first.
    """
    sim = _Similarity(vectors)
    groups: list[list[Candidate]] = []
    by_address: dict[str, int] = {}
    for c in sorted(candidates, key=lead_sort_key):
        address = normalize_address(c.url)
        target = by_address.get(address) if address else None
        if target is None:
            best = None
            for position, group in enumerate(groups):
                if abs(group[0].when - c.when) > window:
                    continue
                score = _affinity(group[0], c, sim, threshold)
                if score is not None and (best is None or score > best[0]):
                    best = (score, position)
            target = best[1] if best else None
        if target is None:
            groups.append([c])
            target = len(groups) - 1
        else:
            groups[target].append(c)
        if address:
            by_address.setdefault(address, target)
    stories = [Story(members=tuple(sorted(g, key=lead_sort_key))) for g in groups]
    return sorted(stories, key=lambda s: lead_sort_key(s.lead))
