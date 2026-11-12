"""Turn planned sections into the brief document, and write its two opening sentences.

Assembly is plain code. The only language-model call in the whole brief is `write_opening`,
and it has a deterministic fallback, so the brief never fails because of the model.
"""

import logging
from datetime import datetime

from sqlmodel import Session, or_, select

from spyglass_service.radar.brief.cluster import Candidate, Story, lead_sort_key, source_key
from spyglass_service.radar.brief.llm import LlmFn, json_schema
from spyglass_service.radar.brief.rank import SectionPlan
from spyglass_service.radar.models import ItemState, RadarBrief, loads
from spyglass_service.radar.profile_defaults import load_profile
from spyglass_service.radar.serialize import _state_dict

logger = logging.getLogger(__name__)

# A story lists at most this many publications; `source_count` still gives the true number.
MAX_LISTED_SOURCES = 8

# Seconds a reader spends per story, by section; used for the "N minute read" estimate.
SECONDS_PER_STORY = {"top": 30, "watch": 15, "notable": 15, "papers": 15, "from_you": 15, "skim": 4}

OPENING_SCHEMA = json_schema("brief_opening", {"opening": {"type": "string"}}, ["opening"])


def distinct_sources(story: Story) -> list[Candidate]:
    """One member per distinct publication: the lead first, then the others best-scored first.

    The same article stored twice (same normalised address) counts once.
    """
    members = story.distinct_members
    seen: set[str] = set()
    kept: list[Candidate] = []
    for m in (members[0], *sorted(members[1:], key=lead_sort_key)):
        key = source_key(m)
        if key not in seen:
            seen.add(key)
            kept.append(m)
    return kept


def story_dict(story: Story, items: dict[int, dict]) -> dict:
    """The Story JSON of the brief contract, built from RadarItem dicts keyed by item id.

    `sources` lists at most MAX_LISTED_SOURCES distinct publications; `source_count` is the
    true number of distinct publications; `member_ids` names every item in the story, so none
    of them is shown again in a later brief.
    """
    lead = items[story.lead.item_id]
    distinct = [m for m in distinct_sources(story) if m.item_id in items]
    sources = [
        {"item_id": m.item_id, "name": items[m.item_id]["origin"] or "", "url": items[m.item_id]["url"]}
        for m in distinct[:MAX_LISTED_SOURCES]
    ]
    return {
        "id": f"s-{lead['id']}",
        "item_id": lead["id"],
        "headline": lead["headline"] or lead["title"],
        "why": lead["why"],
        "section": lead["section"],
        "section_label": lead["section_label"],
        "kind": lead["kind"],
        "score": lead["score"],
        "signal": lead["signal"],
        "entities": lead["entities"],
        "published_at": lead["published_at"],
        "from_user": story.from_user,
        # The watched organisations the story is about, so the interface can name them.
        "watch": [{"name": name, "category": category} for name, category in story.watch],
        "source_count": len(distinct),
        "sources": sources,
        "member_ids": [m.item_id for m in story.members],
        "state": lead["state"],
    }


def read_minutes(plans: list[SectionPlan]) -> int:
    """Estimated minutes to read the brief (at least one)."""
    seconds = sum(SECONDS_PER_STORY[p.key] * len(p.stories) for p in plans)
    return max(1, round(seconds / 60))


def fallback_opening(sections: list[dict], quiet: bool) -> str:
    """Two plain sentences describing the day, built without a model."""
    by_key = {s["key"]: s["stories"] for s in sections}
    top, watch = by_key.get("top", []), by_key.get("watch", [])
    lead = top[0]["headline"].rstrip(".") if top else None
    if quiet and lead:
        first = f"It was a quiet day; the one thing worth noting: {lead}."
    elif quiet:
        first = "It was a quiet day: little crossed the bar for a top story."
    elif lead:
        first = f"The main story today: {lead}."
    else:
        first = "Here is what came in today."
    parts = []
    if top:
        parts.append(f"{len(top)} top {'story' if len(top) == 1 else 'stories'}")
    if watch:
        parts.append(f"{len(watch)} from organisations you watch")
    if not parts:
        return f"{first} Nothing else needs your attention."
    return f"{first} This brief has {' and '.join(parts)}."


def _opening_messages(sections: list[dict], quiet: bool) -> list[dict]:
    """The prompt: only top and watch headlines with their reasons, no other reader detail."""
    lines = []
    for section in sections:
        if section["key"] in ("top", "watch"):
            for st in section["stories"]:
                lines.append(f"- [{section['title']}] {st['headline']}" + (f" ({st['why']})" if st["why"] else ""))
    day = "Today was a quiet day with little of note." if quiet else "Today had real news."
    return [
        {"role": "system", "content": (
            "You write the two-sentence opening of a daily news brief. Write exactly two plain "
            "sentences saying what the day was about, in a neutral tone with no hype and no "
            "greeting. Use only the headlines given. If the day was quiet, say so plainly. "
            'Return JSON: {"opening": "..."}.')},
        {"role": "user", "content": f"{day}\nHeadlines:\n" + ("\n".join(lines) or "(none)")},
    ]


def write_opening(sections: list[dict], quiet: bool, llm: LlmFn | None) -> str:
    """The brief's opening: one model call when `llm` is given, else (or on any failure) the fallback."""
    if llm is not None:
        try:
            text = llm(_opening_messages(sections, quiet), OPENING_SCHEMA).get("opening")
            if isinstance(text, str) and text.strip():
                return text.strip()
            logger.warning("opening: the model returned no text; using the fallback")
        except Exception:  # the brief must never fail because of the model
            logger.exception("opening: model call failed; using the fallback")
    return fallback_opening(sections, quiet)


def story_item_ids(doc: dict) -> set[int]:
    """Every item id a brief document covers: leads, listed sources and all story members."""
    ids: set[int] = set()
    for section in doc.get("sections", []):
        for st in section.get("stories", []):
            ids.add(st["item_id"])
            ids.update(src["item_id"] for src in st.get("sources", []))
            ids.update(st.get("member_ids", []))
    return ids


def story_members(session: Session, item_id: int) -> list[int]:
    """The other items of the story `item_id` belongs to, as listed in the latest brief with it.

    Read from the stored document's `sources`, so the reader's source switcher offers exactly
    what the brief showed. Returns [] when no brief contains the item.
    """
    # Cheap pre-filter on the stored JSON text (written compactly by `dumps`), then parse.
    patterns = [f'%"item_id":{int(item_id)},%', f'%"item_id":{int(item_id)}}}%']
    rows = session.exec(
        select(RadarBrief).where(or_(*(RadarBrief.doc.like(p) for p in patterns)))
        .order_by(RadarBrief.day.desc())
    ).all()
    for row in rows:
        for section in (loads(row.doc, {}) or {}).get("sections", []):
            for st in section.get("stories", []):
                listed = [src["item_id"] for src in st.get("sources", [])]
                if item_id == st.get("item_id") or item_id in listed or item_id in st.get(
                        "member_ids", []):
                    return [i for i in listed if i != item_id]
    return []


def refresh_states(session: Session, doc: dict) -> dict:
    """A copy of the document with each story's `state` block re-read from the database.

    A story's section label is also re-read from the profile, so a section renamed after the
    brief was composed reads the same on Today as everywhere else.
    """
    lead_ids = [st["item_id"] for sec in doc.get("sections", []) for st in sec.get("stories", [])]
    states = {}
    if lead_ids:
        states = {
            s.item_id: s for s in session.exec(select(ItemState).where(ItemState.item_id.in_(lead_ids))).all()
        }
    labels = {s.get("key"): str(s.get("label") or s.get("key"))
              for s in load_profile(session).get("sections", [])}
    sections = []
    for sec in doc.get("sections", []):
        stories = [{**st, "state": _state_dict(states.get(st["item_id"])),
                    "section_label": labels.get(st.get("section"), st.get("section_label", ""))}
                   for st in sec.get("stories", [])]
        sections.append({**sec, "stories": stories})
    return {**doc, "sections": sections}


# A brief is called incomplete only when a meaningful share of the day went unjudged: at least
# this many items, or this fraction of what was collected. One stray failure is not an outage.
DEGRADED_MIN_ITEMS = 10
DEGRADED_MIN_SHARE = 0.05


def is_degraded(unjudged: int, collected: int) -> bool:
    """True when enough of the day's items are unjudged that the brief should say so."""
    if unjudged <= 0:
        return False
    if unjudged >= DEGRADED_MIN_ITEMS:
        return True
    return collected > 0 and unjudged / collected >= DEGRADED_MIN_SHARE


def degraded_notice(unjudged: int) -> str | None:
    """The sentence shown above a brief that is incomplete, or None when nothing is missing."""
    if unjudged <= 0:
        return None
    noun = "item has" if unjudged == 1 else "items have"
    return (f"{unjudged} {noun} not been judged yet, usually because the AI service was "
            "unavailable; this brief is incomplete.")


def build_document(
    day: str,
    generated_at: datetime,
    plans: list[SectionPlan],
    items: dict[int, dict],
    *,
    quiet: bool,
    collected: int,
    llm: LlmFn | None,
    unjudged: set[int] | frozenset[int] = frozenset(),
) -> dict:
    """Assemble the brief document (the contract's shape) from planned sections.

    `unjudged` holds the ids of items in the brief's window that have no usable judgement.
    They are reported as `unjudged` with `degraded` and a `notice`, and never counted in
    `filtered_out` (which means judged and left out).
    """
    sections = [
        {
            "key": p.key,
            "title": p.title,
            "note": p.note,
            "stories": [story_dict(s, items) for s in p.stories],
        }
        for p in plans
    ]
    shown = {m.item_id for p in plans for s in p.stories for m in s.members}
    return {
        "day": day,
        "generated_at": generated_at.isoformat(),
        "opening": write_opening(sections, quiet, llm),
        "quiet": quiet,
        "read_minutes": read_minutes(plans),
        "collected": collected,
        "filtered_out": max(0, collected - len(shown | set(unjudged))),
        "unjudged": len(unjudged),
        "degraded": is_degraded(len(unjudged), collected),
        "notice": degraded_notice(len(unjudged)) if is_degraded(len(unjudged), collected) else None,
        "sections": sections,
    }
