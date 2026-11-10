"""Database schema: collected items, triage cards, feeds, and run logs."""

from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel, UniqueConstraint


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for all schema defaults."""
    return datetime.now(UTC)


class CardState(str, Enum):
    """Triage lifecycle of a dashboard card. Dismissed is archived, never deleted."""

    NEW = "new"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    QUEUED = "queued"
    FINISHED = "finished"


class Item(SQLModel, table=True):
    """A raw collected item from any source, identified by (source, external_id)."""

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_item_source_extid"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    external_id: str
    title: str
    url: str
    summary: str | None = None
    # Tags from the source (e.g. Raindrop tags), comma-joined; used for filtering.
    source_tags: str | None = None
    # Where the item came from: feed title (RSS) / site domain (Raindrop).
    # `source` only names the collector; this names the publication.
    origin: str | None = None
    # Canonical feed URL for RSS items; null for non-RSS sources (e.g. Raindrop).
    # Joins to Feed.feed_url -- the durable key shared with reader.
    feed_url: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=_utcnow)


class Content(SQLModel, table=True):
    """An item's fetched full text, stored as clean markdown inside SQLite.

    One row per item (1:1). `status` records whether the fetch produced usable text
    (ok / empty / failed / paywalled); failures are recorded, never silently dropped.
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    markdown: str
    # Character length of the stored markdown; computed on store for cheap display.
    text_chars: int = 0
    source_url: str | None = None
    content_type: str | None = None
    status: str = "ok"
    error: str | None = None
    fetched_at: datetime = Field(default_factory=_utcnow)
    # Structured, card-visible failure record: populated by
    # documents.fetch_fulltext (via fetch_failure.py) on BOTH success and failure, so a
    # block reads as a legible, re-tryable reason instead of a bare "failed". All four
    # are nullable/defaulted -- an older row (or a lane like YouTube transcript that
    # never touches the acquire ladder) simply leaves them None.
    #
    # The classified/sniffed content kind (transcript/pdf/image/html) or the raw
    # content-type when nothing more specific was determined.
    detected_type: str | None = None
    # The most-escalated acquire() tier reached (e.g. "T0".."T3").
    tier_reached: str | None = None
    # The most informative HTTP status from the attempt trail -- prefers the ORIGINAL
    # block status (e.g. 403) over a later tier's transport-error None.
    http_status: int | None = None
    # A short failure classifier (e.g. "blocked", "http_error", "timeout",
    # "transport_error", "size_cap", "empty_extraction") -- see fetch_failure.py. Note:
    # "empty_extraction" can also appear on a status="empty" (not "failed") row for a
    # DEFERRED capability (image OCR, not built yet) -- a future `error_class IS NOT NULL`
    # query should not treat every non-null row as strictly "failed".
    error_class: str | None = None


class Embedding(SQLModel, table=True):
    """One semantic vector per item. Normalized float32 stored as bytes.

    text_source records what was embedded ('shallow' = title+summary; 'deep' = body, slice 2).
    model+dim are pinned so a model change can re-embed and searches never mix models.
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", unique=True, index=True)
    vector: bytes
    model: str
    dim: int
    text_source: str = "shallow"
    embedded_at: datetime = Field(default_factory=_utcnow)


class Category(SQLModel, table=True):
    """A managed navigation category. Persists with zero cards so a
    newly created, still-empty category stays selectable."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    # User-pinned order for the chips row: null = unpinned, falls after the
    # pinned ones by card count. Only the chips row honours this; dropdowns stay
    # alphabetical.
    position: int | None = Field(default=None)


class Brief(SQLModel, table=True):
    """One generated Daily Brief: a narrative over a window of collected items.

    covers_from/covers_until delimit which cards the brief covered (by Card.created_at);
    consecutive briefs chain their windows so no card is skipped or double-covered.
    item_count counts the featured items, low_count the 'also noticed' tail.
    """

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    covers_from: datetime
    covers_until: datetime
    markdown: str
    item_count: int
    low_count: int
    # The local calendar day (YYYY-MM-DD) this brief windows on. "" for briefs composed
    # before publish-day windowing (covers_from/covers_until remain their source of truth).
    publish_day: str = Field(default="")
    # Whether a person has reviewed this brief. Defaults False; no windowing/compose
    # behavior reads it.
    reviewed: bool = Field(default=False)


class Card(SQLModel, table=True):
    """A curated card shown on the dashboard, produced by the Claude curation step."""

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    state: CardState = Field(default=CardState.NEW, index=True)
    # False until Claude enriches the card (summary + tags). Raw collected cards
    # start uncurated so the dashboard is interactive before any curation runs.
    curated: bool = Field(default=False, index=True)
    summary: str
    tags: str | None = None
    # Claude-assigned topic category (single) and cluster label for "organize
    # into groups". group_label avoids the SQL reserved word "group".
    category: str | None = None
    # AI-assigned baseline category + override flag (net-change learning).
    category_ai: str | None = None
    category_override: bool = Field(default=False)
    # True once a human has set/confirmed this card's category: manual change or review
    # confirmation. The LLM enrichment pass assigns categories; this flag marks the
    # human-verified ones. Defaults False until a person confirms.
    category_confirmed: bool = Field(default=False, index=True)
    group_label: str | None = Field(default=None, index=True)
    # Relevance assessment: current value, the AI's original (for net-change
    # override detection), a one-line reason, and when it was set.
    relevance: str | None = Field(default=None, index=True)
    relevance_ai: str | None = None
    relevance_reason: str | None = None
    # Numeric relevance from the LLM relevance gate (0-100). The legacy `relevance` bucket is
    # derived from this for the current UI; thresholds are applied read-side.
    relevance_score: int | None = Field(default=None, index=True)
    relevance_at: datetime | None = None
    # True when the user's value differs from the AI's -- the learning signal.
    relevance_override: bool = Field(default=False)
    # Holistic user feedback: "up" / "down" / null. Distinct from relevance --
    # there is no AI baseline and no override flag; presence is the learning signal and clearing
    # it removes the signal (no net-change rule). Consumed by the spyglass-preferences skill.
    feedback: str | None = Field(default=None, index=True)
    feedback_at: datetime | None = None
    note: str | None = None
    deep_dive_prompt: str | None = None
    briefing_path: str | None = None
    # The Daily Brief that covered this card; null until a compose pass stamps it.
    # Stamping is what keeps a card out of every subsequent brief's eligibility query.
    brief_id: int | None = Field(default=None, foreign_key="brief.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Highlight(SQLModel, table=True):
    """A reader text highlight on a card.

    The anchor is the quoted text plus optional char offsets into the stored
    markdown; when offsets are missing or stale the quote is found by search.
    """

    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id", index=True)
    quote: str
    start_offset: int | None = None
    end_offset: int | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class RunLog(SQLModel, table=True):
    """One fetch or curation run per source; feeds the Activity tab."""

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    status: str
    detail: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None


class InboxRun(SQLModel, table=True):
    """One pass of the paper inbox, reported by the Claude session doing it.

    status is running / ok / error, as for RunLog. watermark is the newest Slack message the run
    handled; the next run starts after the latest ok run's watermark, so a failed run is retried.
    """

    id: int | None = Field(default=None, primary_key=True)
    status: str = "running"
    papers: int = 0
    watermark: str | None = None
    error: str | None = None
    # The run debrief: one vault note on how the run's papers connect.
    debrief_path: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None


class InboxEntry(SQLModel, table=True):
    """One paper the user shared in the inbox channel: the card it became and the run.

    A paper shared twice gets two entries on one card. The debrief lives in the vault note at
    Card.briefing_path; this row only records where the paper came from.
    """

    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id", index=True)
    run_id: int | None = Field(default=None, index=True)
    # The Slack message: its timestamp (the watermark unit) and the user's own words.
    message_ts: str | None = None
    message_text: str | None = None
    # Whether the paper's full text could be read (False: filed from its abstract or link).
    full_text: bool = False
    filed: bool = False
    added_at: datetime = Field(default_factory=_utcnow)


class Tombstone(SQLModel, table=True):
    """A deleted item's gravestone: keeps (source, external_id) out of re-collection.

    Delete hard-removes an item's rows; this minimal record is what stops the next
    collection from re-adding it (dedupe is by source+external_id)."""

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_tombstone_src_extid"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    external_id: str
    deleted_at: datetime = Field(default_factory=_utcnow)


class Feed(SQLModel, table=True):
    """One subscribed RSS/Atom feed; its feed_url is the durable join key with Item."""

    id: int | None = Field(default=None, primary_key=True)
    # RESOLVED canonical URL passed to reader.add_feed -- the join key with Item.feed_url.
    feed_url: str = Field(unique=True, index=True)
    # Resolved display name (feed title); overridable by the user.
    name: str
    # Set on user rename so periodic re-resolution does not clobber the custom name.
    name_overridden: bool = Field(default=False)
    # Feed format: rss | atom | youtube | other (informational; does not drive logic).
    kind: str
    # Reversible display filter: False hides items in the UI but keeps collecting them.
    enabled: bool = Field(default=True, index=True)
    # Last fetch outcome: ok | error | None (never fetched).
    last_fetch_status: str | None = Field(default=None)
    # Timestamp of the most recent successful fetch, from reader's per-feed last-updated.
    last_fetch_at: datetime | None = Field(default=None)
    # Truncated exception text from the last failed fetch.
    last_error: str | None = Field(default=None)
    # How this feed was added: import | discovery | manual.
    added_via: str
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FetchJob(SQLModel, table=True):
    """One on-demand "fetch full text" request, queued for the background worker.

    Exists so a fetch's progress lives in the database rather than in the reader pane's
    React state, which the dashboard destroys whenever another card is opened.
    `status` is one of queued | running | done | failed; `error` carries the
    structured failure reason when the job ends in `failed`.
    """

    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(index=True)
    status: str = Field(default="queued", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None)


class ClaudeJob(SQLModel, table=True):
    """One background job for one item: a hidden Claude run Spyglass starts.

    kind is prepare-detail (write the item's detailed note) or file-note (file that note in the
    vault). status is queued | running | ok | failed | cancelled. The run reports through the job
    MCP tools: note_path is the note it wrote or where it filed it, and message is its one-line
    report ("Filed to ... because ..."). The rest records what the run cost and why it failed.
    """

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    card_id: int = Field(index=True)
    status: str = Field(default="queued", index=True)
    note_path: str | None = None
    message: str | None = None
    # What a running job is doing now ("Opening Obsidian"), for the item's status line.
    progress: str | None = None
    reported: bool = False
    cancel_requested: bool = False
    error: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    # The model the run used, and how much of the user's Claude limits was used after it
    # (0..1, from the run's rate-limit report): the 5-hour window and the week.
    model: str | None = None
    usage_five_hour: float | None = None
    usage_week: float | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ChatThread(SQLModel, table=True):
    """One in-reader conversation, about a SET of cards.

    The card set lives in ChatThreadCard rather than a card_id here on purpose: the chat scopes
    a conversation to a *selection*, so a per-card foreign key would force a data migration
    once real transcripts exist and cannot be regenerated.

    `rolled_summary` / `rolled_through_id` carry the compaction state. They only
    ever affect what is SENT to the model -- the transcript in ChatMessage is never trimmed,
    so "come back to it in four days" and "do not blow the context window" never compete.
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow, index=True)
    # Older turns condensed once, reused thereafter; None until the first rollover.
    rolled_summary: str | None = Field(default=None)
    # Highest ChatMessage.id covered by rolled_summary; messages above it are sent verbatim.
    rolled_through_id: int | None = Field(default=None)


class ChatThreadCard(SQLModel, table=True):
    """Membership of one card in one chat thread's context set.

    A thread is identified by its card set under SET EQUALITY, not overlap: a conversation
    about {A} and one about {A, B} are different conversations, which is what makes "which
    thread am I in?" answerable at all.
    """

    id: int | None = Field(default=None, primary_key=True)
    thread_id: int = Field(index=True)
    card_id: int = Field(index=True)


class ChatMessage(SQLModel, table=True):
    """One turn of a chat thread -- the durable record.

    Written by the SERVER, including the assistant turn, which is persisted when the stream
    ends even if the client already navigated away. Letting the client post the reply back
    would lose the reply whenever the client navigates away, the same problem as keeping
    fetch progress in the reader pane's state.
    """

    id: int | None = Field(default=None, primary_key=True)
    thread_id: int = Field(index=True)
    role: str  # 'user' | 'assistant'
    content: str
    created_at: datetime = Field(default_factory=_utcnow)
    # Set when a generation failed part-way; the partial content is still kept.
    error: str | None = Field(default=None)


class DomainFetchMethod(SQLModel, table=True):
    """The winning acquire() tier last seen for a domain.

    One row per domain (unique). Written only when a fetch escalated ABOVE T0 and
    succeeded -- a T0-friendly domain is never pinned, so it keeps starting cheap.
    `fetch_fulltext` reads this to pass `start_tier` into `acquire()`, skipping the
    lower-tier attempts a domain is already known to need, so an automatic batch pays
    the escalation cost once per domain instead of once per URL.
    """

    id: int | None = Field(default=None, primary_key=True)
    domain: str = Field(unique=True, index=True)
    tier: str
    updated_at: datetime = Field(default_factory=_utcnow)
