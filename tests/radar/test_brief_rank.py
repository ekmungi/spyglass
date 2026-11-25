"""Tests for story ranking and the section budgets."""

from datetime import datetime, timedelta

import pytest

from spyglass_service.radar.brief import rank
from spyglass_service.radar.brief.cluster import Candidate, Story

NOW = datetime(2026, 11, 12, 12, 0)


def story(item_id: int, score: int = 60, tier: str = "top", **kw) -> Story:
    """A single-item story published an hour ago."""
    kw.setdefault("when", NOW - timedelta(hours=1))
    return Story(members=(Candidate(item_id=item_id, score=score, tier=tier, **kw),))


def keys(plans) -> dict[str, list[int]]:
    """Section key -> lead item ids."""
    return {p.key: [s.lead.item_id for s in p.stories] for p in plans}


def test_rank_adds_coverage_watch_and_reader_bonuses() -> None:
    base = rank.story_rank(story(1, 60, publication="a"), NOW)
    multi = Story(members=tuple(
        Candidate(item_id=i, score=60, when=NOW - timedelta(hours=1), publication=f"p{i}") for i in range(1, 4)
    ))
    assert rank.story_rank(multi, NOW) - base == pytest.approx(10)
    assert rank.story_rank(story(1, 60, watched=True), NOW) - base == pytest.approx(rank.WATCH_BONUS)
    assert rank.story_rank(story(1, 60, from_user=True), NOW) - base == pytest.approx(rank.FROM_USER_BONUS)


def test_coverage_bonus_is_capped() -> None:
    many = Story(members=tuple(
        Candidate(item_id=i, score=60, when=NOW, publication=f"p{i}") for i in range(10)
    ))
    assert rank.story_rank(many, NOW) <= 60 + rank.PUBLICATION_BONUS_MAX + rank.RECENCY_BONUS_MAX


def test_fresher_story_ranks_slightly_higher() -> None:
    fresh = rank.story_rank(story(1, when=NOW - timedelta(hours=1)), NOW)
    stale = rank.story_rank(story(2, when=NOW - timedelta(days=3)), NOW)
    assert fresh > stale


def test_top_is_capped_and_each_story_is_in_exactly_one_section() -> None:
    stories = [story(i, 90 - i) for i in range(1, 12)]
    plans, quiet = rank.build_sections(stories, NOW)
    got = keys(plans)
    assert not quiet
    assert len(got["top"]) == rank.TOP_MAX
    placed = [i for ids in got.values() for i in ids]
    assert len(placed) == len(set(placed))


def test_from_user_stories_are_always_present_without_a_cap() -> None:
    stories = [story(i, 5, tier="out", from_user=True) for i in range(1, 12)]
    plans, _ = rank.build_sections(stories, NOW)
    assert len(keys(plans)["from_you"]) == 11


def test_watch_needs_the_minimum_score_and_is_capped() -> None:
    stories = [story(i, 60, watched=True, competitor=True) for i in range(1, 10)] + [
        story(20, 30, tier="skim", watched=True, competitor=True)]
    got = keys(rank.build_sections(stories, NOW)[0])
    assert len(got["watch"]) == rank.WATCH_MAX
    assert 20 not in got["watch"]
    assert 20 in got["skim"]


def test_papers_section_is_small_and_notes_how_many_were_picked() -> None:
    papers = [story(i, 65 + i, tier="notable", kind="paper", section="health") for i in range(1, 9)]
    plans, _ = rank.build_sections(papers, NOW)
    section = next(p for p in plans if p.key == "papers")
    assert [s.lead.item_id for s in section.stories] == [8, 7, 6]
    assert section.note == "3 picked from 8"


def test_papers_must_be_relevant_and_are_never_padded() -> None:
    """A paper needs tier top or notable, a profile section and a score of at least 70."""
    weak = story(1, 69, tier="notable", kind="paper", section="health")
    no_section = story(2, 90, tier="top", kind="paper", section="")
    other_section = story(3, 90, tier="top", kind="paper", section="oncology")
    good = story(4, 75, tier="notable", kind="paper", section="health")
    plans, _ = rank.build_sections([weak, no_section, other_section, good], NOW,
                                   profile_sections=frozenset({"health", "models"}))
    got = keys(plans)
    assert got["papers"] == [4]
    assert {1, 2, 3}.isdisjoint(got["papers"])


def test_papers_tie_on_score_broken_by_community_upvotes() -> None:
    a = story(1, 70, tier="notable", kind="paper", upvotes=3, section="health")
    b = story(2, 70, tier="notable", kind="paper", upvotes=40, section="health")
    section = next(p for p in rank.build_sections([a, b], NOW)[0] if p.key == "papers")
    assert [s.lead.item_id for s in section.stories] == [2, 1]


def test_paper_of_tier_skim_goes_to_skim_not_papers() -> None:
    plans, _ = rank.build_sections([story(1, 20, tier="skim", kind="paper")], NOW)
    assert keys(plans) == {"skim": [1]}


def test_the_section_cap_applies_to_top_only() -> None:
    """At most three Top stories from one profile section; Worth knowing has no such cap."""
    stories = [story(i, 95 - i, tier="top", section="health") for i in range(1, 7)]
    stories += [story(i, 70 - i, tier="notable", section="models") for i in range(10, 13)]
    got = keys(rank.build_sections(stories, NOW)[0])
    assert got["top"][:3] == [1, 2, 3] and len([i for i in got["top"] if i < 10]) == 3
    assert got["notable"][:3] == [4, 5, 6]  # the strongest left over, health or not


def test_no_skim_story_outranks_a_worth_knowing_story() -> None:
    """Worth knowing is the next best by rank, Skim the next after that."""
    sections = ["health", "health", "health", "health", "models", "labs"]
    stories = [story(i, 90 - i * 2, tier="top" if i < 3 else "notable",
                     section=sections[i % len(sections)]) for i in range(30)]
    stories += [story(100 + i, 40 + i, tier="skim", section="industry") for i in range(10)]
    plans, _ = rank.build_sections(stories, NOW)
    by_key = {p.key: p.stories for p in plans}
    worst_notable = min(rank.story_rank(s, NOW) for s in by_key["notable"])
    best_skim = max(rank.story_rank(s, NOW) for s in by_key["skim"])
    assert best_skim <= worst_notable
    for plan in plans:  # inside every section, best rank first
        ranks = [rank.story_rank(s, NOW) for s in plan.stories]
        assert ranks == sorted(ranks, reverse=True), plan.key


def test_budgets_make_a_short_brief() -> None:
    """A normal day is about 20-25 stories."""
    assert (rank.TOP_MAX, rank.WATCH_MAX, rank.NOTABLE_MAX, rank.PAPERS_MAX, rank.SKIM_MAX) == (
        5, 5, 6, 3, 6)


def test_notable_is_capped_at_eight() -> None:
    sections = ["models", "labs", "agents", "health", "industry", "direction"]
    stories = [story(i, 60 - i, tier="notable", section=sections[i % 6]) for i in range(30)]
    assert len(keys(rank.build_sections(stories, NOW)[0])["notable"]) == rank.NOTABLE_MAX


def test_skim_is_capped_and_holds_the_overflow() -> None:
    stories = [story(i, 30, tier="skim") for i in range(40)]
    assert len(keys(rank.build_sections(stories, NOW)[0])["skim"]) == rank.SKIM_MAX


def test_quiet_day_is_not_padded() -> None:
    stories = [story(1, 80, tier="top"), story(2, 30, tier="skim")]
    plans, quiet = rank.build_sections(stories, NOW)
    assert quiet
    assert keys(plans) == {"top": [1], "skim": [2]}


def test_busy_day_with_few_top_stories_shows_at_least_three() -> None:
    stories = [story(1, 90, tier="top")] + [story(i, 70 - i, tier="notable", section=f"s{i}") for i in range(2, 8)]
    plans, quiet = rank.build_sections(stories, NOW)
    assert not quiet
    assert len(keys(plans)["top"]) == rank.TOP_MIN_BUSY


def test_is_quiet_threshold() -> None:
    assert rank.is_quiet([story(1), story(2)])
    assert not rank.is_quiet([story(1), story(2), story(3, tier="notable")])
    assert rank.is_quiet([])


def test_no_stories_gives_no_sections() -> None:
    assert rank.build_sections([], NOW) == ([], True)


def test_section_titles() -> None:
    plans, _ = rank.build_sections([story(1)], NOW)
    assert plans[0].title == "Top stories"


def test_watched_stories_about_non_competitors_use_the_ordinary_sections() -> None:
    """A story about a watched AI lab or journal is not a competitor story: it is ranked normally."""
    lab = story(1, 80, watched=True, watch=(("Some Lab", "AI labs"),))
    rival = story(2, 70, watched=True, competitor=True, watch=(("Rival Inc", "Surgical robotics"),))
    got = keys(rank.build_sections([lab, rival], NOW)[0])
    assert got["watch"] == [2]
    assert 1 in got["top"] + got.get("notable", []) + got.get("skim", [])
    assert rank.story_rank(lab, NOW) - rank.story_rank(story(3, 80), NOW) == pytest.approx(rank.WATCH_BONUS)


def test_the_watch_section_is_titled_for_the_reader_s_list() -> None:
    plans, _ = rank.build_sections([story(1, 70, competitor=True)], NOW)
    assert [p.title for p in plans if p.key == "watch"] == ["On your watch list"]


def test_a_story_collects_the_watched_organisations_of_all_its_members() -> None:
    a = Candidate(item_id=1, score=60, when=NOW, watch=(("A Co", "Cat"),), competitor=True)
    b = Candidate(item_id=2, score=50, when=NOW, watch=(("A Co", "Cat"), ("B Lab", "AI labs")))
    merged = Story(members=(a, b))
    assert merged.watch == (("A Co", "Cat"), ("B Lab", "AI labs")) and merged.competitor


def run(start: int, count: int, score: int, tier: str, **kw) -> list[Story]:
    """`count` stories with ids from `start` and the same score and tier (equal rank, id order)."""
    return [story(start + i, score, tier=tier, **kw) for i in range(count)]


def more_of(plans) -> dict[str, list[int]]:
    """Section key -> lead item ids of the unpicked stories kept under it."""
    return {p.key: [s.lead.item_id for s in p.more] for p in plans}


def test_left_over_stories_go_to_the_first_section_that_fits() -> None:
    picked_top = [story(1000 + i, 100 - i, tier="top") for i in range(5)]
    picked_notable = [story(1100 + i, 95 - i, tier="notable") for i in range(6)]
    picked_skim = [story(1200 + i, 89 - i, tier="skim") for i in range(6)]
    watch = run(100, 5, 80, "notable", competitor=True)  # the five watch slots
    papers = run(200, 3, 75, "notable", kind="paper", section="health")  # all three are picked
    left = [
        # An eligible paper (score 70) ranks below the not eligible one (score 69, but fresher).
        story(204, 70, tier="notable", kind="paper", section="health", when=NOW - timedelta(days=3)),
        story(205, 69, tier="notable", kind="paper", section="health", when=NOW - timedelta(minutes=1)),
        story(106, 60, tier="notable", competitor=True),
        story(401, 55, tier="notable"),
        story(301, 50, tier="top"),
        story(107, 30, tier="skim", competitor=True),  # too weak for the watch list
        story(501, 40, tier="skim"),
    ]
    plans, _ = rank.build_sections(
        picked_top + picked_notable + picked_skim + watch + papers + left, NOW)
    got = more_of(plans)
    assert got["watch"] == [106]
    assert got["papers"] == [204, 205]  # eligible papers first, then the others
    assert got["top"] == [301]
    assert got["notable"] == [401]
    assert got["skim"] == [501, 107]
    # Each left-over story is in exactly one `more`, and none of them is a picked story.
    flat = [i for ids in got.values() for i in ids]
    assert len(flat) == len(set(flat)) == 7
    assert not set(flat) & {s.lead.item_id for p in plans for s in p.stories}


def test_a_section_without_picked_stories_takes_none() -> None:
    # No paper is eligible, so there is no Papers section: the paper falls through to Worth knowing.
    stories = (run(1, 5, 99, "top") + run(10, 6, 90, "notable") + run(20, 6, 60, "skim")
               + [story(30, 30, tier="notable", kind="paper", section="health")])
    plans, _ = rank.build_sections(stories, NOW)
    assert "papers" not in keys(plans)
    assert more_of(plans)["notable"] == [30]


def test_more_is_capped_at_twelve_and_pool_counts_all() -> None:
    plans, _ = rank.build_sections([story(i, 100 - i, tier="skim") for i in range(1, 26)], NOW)
    skim = next(p for p in plans if p.key == "skim")
    assert rank.MORE_MAX == 12
    assert len(skim.stories) == rank.SKIM_MAX
    assert [s.lead.item_id for s in skim.more] == list(range(rank.SKIM_MAX + 1, rank.SKIM_MAX + 13))
    assert skim.pool == 25  # the picked six plus all nineteen left over


def test_from_you_has_no_more() -> None:
    stories = run(1, 3, 5, "out", from_user=True) + run(10, 9, 40, "skim")
    plans, _ = rank.build_sections(stories, NOW)
    from_you = next(p for p in plans if p.key == "from_you")
    assert from_you.more == () and from_you.pool == 3
    assert [s.lead.item_id for s in next(p for p in plans if p.key == "skim").more] == [16, 17, 18]


def test_a_story_whose_lead_has_no_headline_is_not_kept() -> None:
    stories = run(1, 6, 60, "skim") + [
        story(7, 50, tier="skim"), story(8, 45, tier="skim", has_headline=False),
        story(9, 40, tier="skim")]
    skim = next(p for p in rank.build_sections(stories, NOW)[0] if p.key == "skim")
    assert [s.lead.item_id for s in skim.more] == [7, 9]
    assert skim.pool == 8  # the story without a headline is not counted either
