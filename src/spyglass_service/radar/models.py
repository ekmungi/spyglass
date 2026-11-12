"""Radar tables: assessments, reader documents, briefs, user state, assistant threads, watch.

Every table here is additive: it references `item.id` and never alters the engine's own
tables, so the older API keeps working beside it. JSON values are stored as TEXT; use
`dumps`/`loads` below so an empty column never raises.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Field, SQLModel, UniqueConstraint

# The radar tables point at item.id, so the engine's tables must be registered first.
import spyglass_service.models  # noqa: F401, E402


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for all radar defaults."""
    return datetime.now(UTC)


def dumps(value: Any) -> str:
    """Serialize a JSON-able value for a TEXT column (compact, unicode kept)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(raw: str | None, default: Any = None) -> Any:
    """Parse a TEXT column holding JSON; return `default` for NULL, empty or corrupt text."""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


# Tier values, best first. "out" items never reach a brief and are hidden from the default feed.
# "unjudged" marks a failed triage (the model's reply was unusable): not a judgement at all.
TIERS = ("top", "notable", "skim", "out", "unjudged")
# What kind of thing an item is; drives the brief's Papers section and the reader layout.
KINDS = ("news", "release", "research", "paper", "post", "video", "regulatory", "tool", "opinion")


class RadarDoc(SQLModel, table=True):
    """A named JSON document: the profile, the engine list, small caches.

    One row per key. Known keys: "profile", "engines", "papers:<query>".
    """

    key: str = Field(primary_key=True)
    # The document itself, as JSON text. (Not named `json`: that would shadow a base-class attribute.)
    body: str
    updated_at: datetime = Field(default_factory=utcnow)


class Assessment(SQLModel, table=True):
    """The judgement of one item against the reader's profile.

    stage "triage" means only title and snippet were judged (score, section, kind). stage
    "digest" means the full text was read and headline, why, key_points, entities and
    event_key are filled.
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    stage: str = "triage"
    # 0-100 relevance to the profile; the tier is derived from it and from the item's kind.
    score: int = Field(default=0, index=True)
    tier: str = Field(default="out", index=True)
    # Key of a profile section, e.g. "models" or "health".
    section: str = Field(default="", index=True)
    kind: str = "news"
    # A plain rewritten headline of at most about 12 words.
    headline: str | None = None
    # One or two sentences: why this matters to this reader.
    why: str | None = None
    # JSON list[str] of at most 4 short key points (the summary shown above the reader).
    key_points: str | None = None
    # JSON list[str] of organisations named in the item (used for watch matching and discovery).
    entities: str | None = None
    # Short slug naming the underlying event, shared by items that report the same thing.
    event_key: str | None = Field(default=None, index=True)
    model: str | None = None
    # Version of the profile this was judged against; a newer profile may re-judge.
    profile_version: int = 0
    # Failed triage attempts (the model answered, but not usably). Stage "triage_failed" items
    # are triaged again on later runs until this reaches the pipeline's limit.
    triage_attempts: int = 0
    # Failed digest attempts; after the pipeline's limit the item keeps its triage judgement.
    digest_attempts: int = 0
    # The last error text of a failed attempt. Never shown to the reader as "why".
    error: str | None = None
    assessed_at: datetime = Field(default_factory=utcnow)


class ItemState(SQLModel, table=True):
    """What the reader did with an item, and whether the reader sent it in."""

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    # True when the reader captured the item (Slack, Raindrop, email to self, pasted link).
    from_user: bool = Field(default=False, index=True)
    captured_via: str | None = None
    # When the reader last sent the item in (every capture sets it, also for a known item).
    # The brief's "From you" window reads this; older rows fall back to the item's fetch time.
    captured_at: datetime | None = None
    user_note: str | None = None
    saved_at: datetime | None = Field(default=None, index=True)
    opened_at: datetime | None = None
    open_count: int = 0
    read_seconds: int = 0
    # "more" / "less" / None: the explicit more-like-this signal.
    vote: str | None = None
    # Vault-relative path of a note written by an earlier version's direct save; nothing sets it now
    # (filing is recorded in ItemExtra "filed"). Kept so old rows keep their items from clean-up.
    vault_path: str | None = None
    hidden: bool = False
    updated_at: datetime = Field(default_factory=utcnow)


class Signal(SQLModel, table=True):
    """Append-only log of reader behaviour; the raw material for learning the profile.

    kind is one of: open, dwell, save, unsave, vote, ask, share, vault, expand, capture.
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int | None = Field(default=None, index=True)
    kind: str = Field(index=True)
    value: str | None = None
    at: datetime = Field(default_factory=utcnow)


class ItemExtra(SQLModel, table=True):
    """Source-specific facts about an item, as one JSON object.

    Known keys: points (Hacker News), upvotes (community paper votes), publisher, authors,
    arxiv_id, video_id, comments_url, query (the search that found it).
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    data: str = "{}"


class ReaderDoc(SQLModel, table=True):
    """The clean, sanitized HTML shown in the reader for one item.

    kind: article / paper / pdf / video / email / note. `html` is already sanitized and safe to
    inject. The plain text used by the assistant and by search stays in the engine's Content
    table.
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    kind: str = "article"
    html: str = ""
    title: str | None = None
    byline: str | None = None
    site: str | None = None
    lead_image: str | None = None
    word_count: int = 0
    source_url: str | None = None
    # A second address for the same work: the PDF of a paper, or its HTML edition.
    alt_url: str | None = None
    status: str = "ok"
    error: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)


class RadarBrief(SQLModel, table=True):
    """One day's brief as a structured JSON document (see the build contract for its shape)."""

    id: int | None = Field(default=None, primary_key=True)
    # Local calendar day, YYYY-MM-DD. One brief per day; regenerating replaces the document.
    day: str = Field(unique=True, index=True)
    doc: str
    story_count: int = 0
    collected_count: int = 0
    read_minutes: int = 0
    # When the brief was first composed. Regenerating it does not move this, because the next
    # day's "From you" and "collected" windows start here.
    created_at: datetime = Field(default_factory=utcnow)
    # When the brief was last regenerated (None until it is composed a second time).
    regenerated_at: datetime | None = None
    opened_at: datetime | None = None


class AssistThread(SQLModel, table=True):
    """One assistant conversation, attached to an item, to a day's brief, or to neither."""

    id: int | None = Field(default=None, primary_key=True)
    item_id: int | None = Field(default=None, index=True)
    brief_day: str | None = Field(default=None, index=True)
    title: str = ""
    engine: str | None = None
    model: str | None = None
    # Session id of an external agent process that keeps its own history, when the engine has one.
    external_session: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AssistMessage(SQLModel, table=True):
    """One turn in an assistant thread. `selection` is the passage the question refers to."""

    id: int | None = Field(default=None, primary_key=True)
    thread_id: int = Field(foreign_key="assistthread.id", index=True)
    role: str
    content: str = ""
    selection: str | None = None
    # Preset used, if any: explain, relevance, colleagues, linkedin, blog.
    action: str | None = None
    engine: str | None = None
    model: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class WatchEntity(SQLModel, table=True):
    """A company, lab, regulator or person the reader follows.

    status: active (checked daily) / suggested (waiting for the reader's yes) / muted.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    # company / lab / regulator / person / publication
    kind: str = "company"
    # Free-text group shown in the register, e.g. "Endoscopy AI" or "AI labs".
    category: str = Field(default="", index=True)
    # The profile topic this entity was found for.
    topic: str | None = None
    # JSON list[str] of other names the entity goes by.
    aliases: str | None = None
    # The news search that finds this entity's events.
    query: str | None = None
    website: str | None = None
    feed_url: str | None = None
    status: str = Field(default="suggested", index=True)
    why: str | None = None
    # seed / discovered / user
    added_via: str = "seed"
    created_at: datetime = Field(default_factory=utcnow)
    last_hit_at: datetime | None = None


class ItemEntity(SQLModel, table=True):
    """Link between an item and a watched entity it is about."""

    __table_args__ = (UniqueConstraint("item_id", "entity_id", name="uq_item_entity"),)

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    entity_id: int = Field(foreign_key="watchentity.id", index=True)
    # query (found by the entity's news search) / mention (named in the item's text)
    via: str = "query"
