"""The reader's profile: read, validate and save it, derive examples from history, render it.

The profile (RadarDoc key "profile") is what every relevance judgement is made against. The
examples are titles the reader liked or disliked, read from their own history, so the judging
model calibrates on real behaviour rather than on a handful of bullet points.

What the judging model learns about the reader is bounded: with `privacy_send_examples` off no
example title is sent at all, and when it is on only titles of items the radar itself placed in
one of the profile's sections (with a tier other than "out") qualify, at most 25 of each kind.
A personal bookmark about money or family health, say, is never judged into a section and so
never becomes an example.
"""

import copy
import logging
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from pydantic import model_validator
from sqlmodel import Session, or_, select

from spyglass_service.models import Card, Item
from spyglass_service.radar.models import Assessment, ItemState, RadarDoc, dumps, utcnow
from spyglass_service.radar.profile_defaults import PROFILE_KEY, load_profile

# Titles shorter than this carry too little meaning to calibrate on ("Claude Code", a session id).
MIN_TITLE_CHARS = 15
# Long titles are cut so the example list stays a small, cache-friendly part of the prompt.
TITLE_CAP = 140
# Suffixes that sites append to titles; they add nothing to the meaning.
_TITLE_SUFFIXES = (" - YouTube", " | LinkedIn", " - LinkedIn")

logger = logging.getLogger(__name__)

# The most example titles of each kind ever sent to the judging model.
MAX_EXAMPLES = 25

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ProfileError(ValueError):
    """Raised when a profile document does not have the required shape."""


class ProfileSection(BaseModel):
    """One section of the brief: a stable key, an editable label and a description."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: ShortText
    description: str = Field(default="", max_length=600)


class ProfileTopic(BaseModel):
    """A topic the reader follows, optionally tied to a section key."""

    model_config = ConfigDict(extra="ignore")

    name: ShortText
    section: str = ""


class ProfileDoc(BaseModel):
    """The whole profile document. Unknown keys are dropped; `version` is set on save."""

    model_config = ConfigDict(extra="ignore")

    version: int = 0
    statement: str = Field(min_length=1, max_length=2000)
    sections: list[ProfileSection] = Field(min_length=1, max_length=20)
    topics: list[ProfileTopic] = Field(default_factory=list, max_length=100)
    avoid: list[ShortText] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _check_keys(self) -> "ProfileDoc":
        """Section keys must be unique and every topic must name a known section (or none)."""
        keys = [s.key for s in self.sections]
        if len(set(keys)) != len(keys):
            raise ValueError("section keys must be unique")
        for topic in self.topics:
            if topic.section and topic.section not in keys:
                raise ValueError(f"topic {topic.name!r} names unknown section {topic.section!r}")
        return self


def validate_profile(doc: object) -> dict:
    """Return a clean copy of `doc` in the profile shape, or raise ProfileError explaining why."""
    if not isinstance(doc, dict):
        raise ProfileError("profile must be a JSON object")
    try:
        return ProfileDoc.model_validate(doc).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "profile"
        raise ProfileError(f"{where}: {first.get('msg', 'invalid value')}") from exc


def get_profile(session: Session) -> dict:
    """Return the stored profile (or the default) as an independent copy safe to modify."""
    return copy.deepcopy(load_profile(session))


def save_profile(session: Session, doc: object) -> dict:
    """Validate `doc`, set its version to the stored version plus one, store and return it."""
    clean = validate_profile(doc)
    current = load_profile(session)
    saved = {**clean, "version": int(current.get("version") or 0) + 1}
    row = session.get(RadarDoc, PROFILE_KEY)
    if row is None:
        row = RadarDoc(key=PROFILE_KEY, body=dumps(saved))
    else:
        row.body = dumps(saved)
        row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return saved


def _naive_utc(value: datetime | None) -> datetime:
    """Comparable UTC timestamp: SQLite hands back naive values, new rows may be aware."""
    if value is None:
        return datetime.min
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def clean_title(title: str | None) -> str | None:
    """A title fit for the example list, or None when it is too short to mean anything."""
    text = " ".join((title or "").split())
    for suffix in _TITLE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip()
    if len(text) < MIN_TITLE_CHARS:
        return None
    return text if len(text) <= TITLE_CAP else text[: TITLE_CAP - 1].rstrip() + "…"


def _history_rows(session: Session) -> list[tuple[datetime, int, str, str]]:
    """Every like/dislike signal as (when, item id, title, "liked"|"disliked")."""
    rows: list[tuple[datetime, int, str, str]] = []
    states = session.exec(
        select(ItemState, Item)
        .join(Item, Item.id == ItemState.item_id)
        .where(or_(ItemState.saved_at.is_not(None), ItemState.vote.in_(("more", "less")),
                   ItemState.from_user == True))  # noqa: E712 -- SQL comparison, not Python
    ).all()
    for state, item in states:
        label = "disliked" if state.vote == "less" and state.saved_at is None else "liked"
        # A save has its own time; a vote moves updated_at; an item that was only sent in
        # dates from when it arrived (a later backfill must not make it look new).
        if state.saved_at is not None:
            when = state.saved_at
        elif state.vote in ("more", "less"):
            when = state.updated_at
        else:
            when = item.fetched_at
        rows.append((_naive_utc(when), item.id, item.title, label))
    cards = session.exec(
        select(Card, Item)
        .join(Item, Item.id == Card.item_id)
        .where(Card.feedback.in_(("up", "down")))
    ).all()
    for card, item in cards:
        label = "liked" if card.feedback == "up" else "disliked"
        rows.append((_naive_utc(card.feedback_at or item.fetched_at), item.id, item.title, label))
    for item in session.exec(select(Item).where(Item.source == "raindrop")).all():
        rows.append((_naive_utc(item.fetched_at), item.id, item.title, "liked"))
    return rows


def examples_switch(settings: object | None) -> bool:
    """Whether example titles may be sent: `privacy_send_examples` of `settings`.

    With no settings given, the settings in effect (environment, .env and the dashboard overlay)
    decide; when they cannot be loaded, no examples are sent.
    """
    if settings is not None:
        return bool(getattr(settings, "privacy_send_examples", False))
    from spyglass_service.config import Settings, apply_overlay

    try:
        return bool(apply_overlay(Settings()).privacy_send_examples)
    except Exception:  # noqa: BLE001 -- unknown means off: nothing is sent
        logger.warning("settings could not be loaded; no example titles will be sent")
        return False


def _in_section_ids(session: Session, item_ids: set[int]) -> set[int]:
    """The items the radar judged into one of the profile's sections with a tier other than out."""
    if not item_ids:
        return set()
    keys = set(section_keys(load_profile(session)))
    rows = session.exec(select(Assessment.item_id, Assessment.section, Assessment.tier)
                        .where(Assessment.item_id.in_(item_ids))).all()
    return {item_id for item_id, section, tier in rows if section in keys and tier != "out"}


def refresh_examples(session: Session, max_each: int = MAX_EXAMPLES, *,
                     settings: object | None = None) -> dict:
    """Derive {"liked": [titles], "disliked": [titles]} from the reader's history, newest first.

    Liked: saved, voted "more", sent in by the reader, legacy thumbs-up, Raindrop bookmarks.
    Disliked: voted "less", legacy thumbs-down. When one item has both kinds of signal, the most
    recent one decides. Titles that are too short to carry meaning, and repeats, are skipped.

    Privacy bounds: empty lists when `privacy_send_examples` is off (see `examples_switch`);
    otherwise only items judged into a profile section with a tier other than "out" qualify, and
    `max_each` is capped at `MAX_EXAMPLES`.
    """
    if max_each < 0:
        raise ValueError("max_each must be zero or more")
    if not examples_switch(settings):
        return {"liked": [], "disliked": []}
    max_each = min(max_each, MAX_EXAMPLES)
    history = _history_rows(session)
    allowed = _in_section_ids(session, {row[1] for row in history})
    rows = sorted((r for r in history if r[1] in allowed), key=lambda r: (r[0], r[1]), reverse=True)
    seen_items: set[int] = set()
    seen_titles: set[str] = set()
    out: dict[str, list[str]] = {"liked": [], "disliked": []}
    for _when, item_id, title, label in rows:
        if item_id in seen_items:
            continue
        seen_items.add(item_id)
        text = clean_title(title)
        if text is None or text.lower() in seen_titles or len(out[label]) >= max_each:
            continue
        seen_titles.add(text.lower())
        out[label].append(text)
    return out


def _bullets(lines: list[str]) -> str:
    """Render lines as a dash list, or "(none)" when empty."""
    return "\n".join(f"- {line}" for line in lines) if lines else "- (none)"


def profile_prompt_block(profile: dict, examples: dict | None) -> str:
    """Render the profile and examples as prompt text, most stable parts first.

    The statement, sections, topics and avoid-list change rarely; the examples change as the
    reader votes, so they come last and the long stable prefix stays cacheable.
    """
    sections = [
        f"{s.get('key')} ({s.get('label', s.get('key'))}): {s.get('description', '')}".rstrip(": ")
        for s in profile.get("sections", [])
    ]
    topics = [
        f"{t.get('name')}" + (f" [{t['section']}]" if t.get("section") else "")
        for t in profile.get("topics", [])
    ]
    examples = examples or {}
    parts = [
        "THE READER\n" + str(profile.get("statement", "")).strip(),
        "SECTIONS (use these keys)\n" + _bullets(sections),
        "TOPICS THE READER FOLLOWS\n" + _bullets(topics),
        "AVOID (always score under 20)\n" + _bullets([str(a) for a in profile.get("avoid", [])]),
        "ITEMS THE READER LIKED (newest first)\n" + _bullets(list(examples.get("liked", []))),
        "ITEMS THE READER DISLIKED (newest first)\n" + _bullets(list(examples.get("disliked", []))),
    ]
    return "\n\n".join(parts)


def section_keys(profile: dict) -> list[str]:
    """The section keys the profile defines, in order."""
    return [str(s["key"]) for s in profile.get("sections", []) if s.get("key")]
