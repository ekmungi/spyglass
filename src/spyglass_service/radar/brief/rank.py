"""Rank stories and fill the brief's sections within fixed budgets.

The budgets are what make the brief finite: whatever the day brings, each section has a
ceiling, a story is placed in exactly one section, and a quiet day is allowed to be short.
Inside every section stories are in rank order, and the general sections never invert: Worth
knowing holds the next best stories after Top, and Skim the next after Worth knowing. The only
diversity rule (at most TOP_PER_SECTION stories from one profile section) applies to Top.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from spyglass_service.radar.brief.cluster import Story, lead_sort_key

# --- Budgets (a normal day is about 20-25 stories and about five minutes) ------------------
TOP_MAX = 5            # Top stories: the few things most worth knowing today.
TOP_MIN_BUSY = 3       # On a non-quiet day with few "top" stories, still show at least this many.
TOP_PER_SECTION = 3    # At most this many Top stories from one profile section.
WATCH_MAX = 5          # On your watch list: stories about companies and regulators on the register.
WATCH_MIN_SCORE = 45   # A watched story needs this lead score, so passing mentions stay out.
PAPERS_MAX = 3         # Papers: a small separate section, never padded.
PAPER_MIN_SCORE = 70   # A paper needs at least this score (and a profile section) for a slot.
NOTABLE_MAX = 6        # Worth knowing.
SKIM_MAX = 6           # Skim: headline only.
QUIET_BELOW = 3        # Fewer than this many top/notable stories makes the day quiet.
WORTH_TIERS = ("top", "notable")

# --- Rank bonuses --------------------------------------------------------------------------
PUBLICATION_BONUS = 5       # Per additional publication that reported the event...
PUBLICATION_BONUS_MAX = 15  # ...up to this total.
WATCH_BONUS = 8             # The story is about any watched organisation.
FROM_USER_BONUS = 6         # The reader sent it in.
RECENCY_BONUS_MAX = 4.0     # A story from the last hour gets this; it decays to 0 over the window.
RECENCY_WINDOW = timedelta(days=4)

SECTION_TITLES = {
    "top": "Top stories",
    "watch": "On your watch list",
    "notable": "Worth knowing",
    "papers": "Papers",
    "from_you": "From you",
    "skim": "Skim",
}
# Display order in the document.
SECTION_ORDER = ("top", "watch", "notable", "papers", "from_you", "skim")


@dataclass(frozen=True)
class SectionPlan:
    """One filled section: its key, an optional note such as "5 picked from 96", and stories."""

    key: str
    stories: tuple[Story, ...]
    note: str | None = None

    @property
    def title(self) -> str:
        """The section heading shown to the reader."""
        return SECTION_TITLES[self.key]


def story_rank(story: Story, now: datetime) -> float:
    """Sort value of a story: lead score plus bonuses for coverage, watch, reader and recency."""
    extra_pubs = max(0, story.publications - 1)
    rank = float(story.lead.score) + min(PUBLICATION_BONUS_MAX, PUBLICATION_BONUS * extra_pubs)
    if story.watched:
        rank += WATCH_BONUS
    if story.from_user:
        rank += FROM_USER_BONUS
    age = now - story.lead.when
    if age < RECENCY_WINDOW:
        rank += RECENCY_BONUS_MAX * max(0.0, 1 - age / RECENCY_WINDOW)
    return rank


def is_quiet(stories: list[Story], unjudged: int = 0) -> bool:
    """A day is quiet when fewer than `QUIET_BELOW` stories are tier top or notable.

    A day with items that could not be judged is never quiet: nobody knows what they held.
    """
    if unjudged > 0:
        return False
    return sum(1 for s in stories if s.lead.tier in ("top", "notable")) < QUIET_BELOW


def paper_eligible(story: Story, profile_sections: frozenset[str] | None = None) -> bool:
    """True when a story may take a Papers slot.

    It must be a paper of tier top or notable, scored at least PAPER_MIN_SCORE, and filed under
    one of the reader's profile sections (any non-empty section when they are not given).
    """
    lead = story.lead
    in_profile = bool(lead.section) and (profile_sections is None
                                         or lead.section in profile_sections)
    return (lead.kind == "paper" and lead.tier in WORTH_TIERS
            and lead.score >= PAPER_MIN_SCORE and in_profile)


def _top_capped(pool: list[Story], limit: int) -> list[Story]:
    """The best `limit` stories of `pool` with at most TOP_PER_SECTION from one profile section.

    Stories without a section are not capped (there is nothing to diversify on).
    """
    chosen: list[Story] = []
    counts: dict[str, int] = {}
    for s in pool:
        if len(chosen) >= limit:
            break
        section = s.lead.section
        if section and counts.get(section, 0) >= TOP_PER_SECTION:
            continue
        counts[section] = counts.get(section, 0) + 1
        chosen.append(s)
    return chosen


def _leading_worth_knowing(pool: list[Story]) -> list[Story]:
    """Worth knowing: the next stories in rank order while they are tier top or notable.

    It stops at the first story of another tier, so no Skim story ever outranks a Worth
    knowing story.
    """
    chosen: list[Story] = []
    for s in pool:
        if len(chosen) >= NOTABLE_MAX or s.lead.tier not in WORTH_TIERS:
            break
        chosen.append(s)
    return chosen


def build_sections(stories: list[Story], now: datetime, *, unjudged: int = 0,
                   profile_sections: frozenset[str] | None = None
                   ) -> tuple[list[SectionPlan], bool]:
    """Place stories into sections under the budgets; returns (sections in order, quiet flag).

    Each story lands in the first section that claims it, in this order: from_you, watch,
    papers, top, notable, skim. Empty sections are omitted from the result. `unjudged` is the
    number of items in the brief's window that could not be judged (see `is_quiet`);
    `profile_sections` are the reader's section keys (see `paper_eligible`).
    """
    quiet = is_quiet(stories, unjudged)
    ranks = {id(s): story_rank(s, now) for s in stories}
    ordered = sorted(stories, key=lambda s: (-ranks[id(s)], lead_sort_key(s.lead)))
    remaining = list(ordered)
    picked: dict[str, list[Story]] = {}
    notes: dict[str, str] = {}

    def take(key: str, chosen: list[Story]) -> None:
        """Record the chosen stories under `key` and remove them from the pool."""
        picked[key] = chosen
        ids = {id(s) for s in chosen}
        remaining[:] = [s for s in remaining if id(s) not in ids]

    take("from_you", [s for s in remaining if s.from_user])
    # Only stories about companies and regulators: AI labs, journals and research centres are
    # watched too, but their stories compete for the ordinary sections (WATCH_SECTION_KINDS).
    take("watch", [s for s in remaining if s.competitor and s.lead.score >= WATCH_MIN_SCORE][:WATCH_MAX])

    papers = [s for s in remaining if s.lead.kind == "paper"]
    # Papers that are weak or outside the reader's field get no slot (and the section is never
    # padded); they can still appear further down by rank.
    eligible = [s for s in papers if paper_eligible(s, profile_sections)]
    eligible.sort(key=lambda s: (-ranks[id(s)], -max(m.upvotes for m in s.members)))
    best = eligible[:PAPERS_MAX]
    if best:
        notes["papers"] = f"{len(best)} picked from {len(papers)}"
    take("papers", best)

    tops = [s for s in remaining if s.lead.tier == "top"]
    if len(tops) >= TOP_MIN_BUSY or quiet:
        chosen_top = _top_capped(tops, TOP_MAX)
    else:
        # A busy day without enough "top" stories: fill up to the minimum with the best rest.
        chosen_top = _top_capped([s for s in remaining if s.lead.tier in WORTH_TIERS], TOP_MIN_BUSY)
    take("top", chosen_top)
    take("notable", _leading_worth_knowing(remaining))
    take("skim", remaining[:SKIM_MAX])

    plans = [
        SectionPlan(key=k, stories=tuple(picked[k]), note=notes.get(k))
        for k in SECTION_ORDER
        if picked.get(k)
    ]
    return plans, quiet
