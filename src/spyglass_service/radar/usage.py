"""The usage table: one row per model call, so the reader can see what the assistant and the
judging jobs cost and how much of each request the provider read from its cache.

`record_call` writes a row for code that holds a database engine (the assistant). The bulk judging
calls only hold the settings, so they run inside `call_scope`, which names the purpose and the
settings, and the provider code reports figures with `note_call`. Recording is a side record: a
failure to write is logged and never reaches the call it describes. The table is created
on a fresh database by `init_db` and, for a database that already exists, the first write creates it.
"""

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import delete, inspect, text
from sqlmodel import Field, Session, SQLModel

from spyglass_service.radar.models import utcnow
from spyglass_service.radar.usage_parse import Tokens

logger = logging.getLogger(__name__)

# What a model call was for. `other` covers the small writing jobs without a name of their own.
PURPOSES = ("chat", "feed_chat", "triage", "digest", "brief_opening", "watch_review", "discovery",
            "filing", "other")
# How the judging roles map to a purpose when the caller does not name one.
_ROLE_PURPOSE = {"triage": "triage", "digest": "digest"}


class UsageCall(SQLModel, table=True):
    """One model call. Token figures are None when the provider did not report them."""

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    purpose: str = Field(index=True)
    provider: str
    model: str = ""
    # Tokens outside the cache, tokens written to it, tokens read from it, and tokens produced.
    input_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_read_tokens: int | None = None
    output_tokens: int | None = None
    # The provider's own cost figure for this call alone. For a plan it is the list price of the
    # same work on the API.
    cost_usd: float | None = None
    # What the provider reported before this call's share was taken out: Claude Code reports the
    # whole conversation's cost on a resumed turn, so the share is the difference.
    cost_total: float | None = None
    # True when the turn started a new session from a short summary of the earlier conversation.
    condensed: bool = False
    # True when the turn started a new session (nothing was resumed).
    fresh: bool = False
    duration_ms: int | None = None
    # For a chat: the conversation and the stored answer this call produced.
    thread_id: int | None = Field(default=None, index=True)
    message_id: int | None = None


# (settings, purpose) of the call in progress on this thread of execution, set by `call_scope`.
_SCOPE: ContextVar[tuple[object, str] | None] = ContextVar("usage_scope", default=None)


# Columns added after the table first existed: name -> SQL type, added to an older table on first use.
_LATER_COLUMNS = {"cost_total": "FLOAT", "condensed": "BOOLEAN NOT NULL DEFAULT 0",
                  "fresh": "BOOLEAN NOT NULL DEFAULT 0"}


def ensure_table(engine) -> None:
    """Create the table when the database does not have it, and add any column an older version
    of it lacks. Cheap enough to call before every write."""
    UsageCall.__table__.create(engine, checkfirst=True)  # type: ignore[attr-defined]
    have = {column["name"] for column in inspect(engine).get_columns("usagecall")}
    missing = {name: ddl for name, ddl in _LATER_COLUMNS.items() if name not in have}
    if missing:
        with engine.begin() as connection:
            for name, ddl in missing.items():
                connection.execute(text(f"ALTER TABLE usagecall ADD COLUMN {name} {ddl}"))


def default_purpose(role: str) -> str:
    """The purpose recorded for a judging role: triage and digest keep their names, else `other`."""
    return _ROLE_PURPOSE.get(role, "other")


def record_call(engine, *, purpose: str, provider: str, model: str, tokens: Tokens | None,
                duration_ms: int | None = None, thread_id: int | None = None,
                message_id: int | None = None, cost_total: float | None = None,
                condensed: bool = False, fresh: bool = False) -> int | None:
    """Store one row and return its id; log and return None when it cannot be stored.

    `tokens` None records a call whose figures are unknown (the provider reported none).
    """
    tokens = tokens or Tokens()
    try:
        # Existing databases predate this table; the first write creates or upgrades it.
        ensure_table(engine)
        row = UsageCall(
            purpose=purpose if purpose in PURPOSES else "other", provider=provider, model=model,
            input_tokens=tokens.input, cache_write_tokens=tokens.cache_write,
            cache_read_tokens=tokens.cache_read, output_tokens=tokens.output,
            cost_usd=tokens.cost_usd, cost_total=cost_total, condensed=condensed, fresh=fresh,
            duration_ms=duration_ms, thread_id=thread_id, message_id=message_id)
        with Session(engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id
    except Exception:  # noqa: BLE001 -- recording must never break the call it describes
        logger.warning("could not record a model call's usage", exc_info=True)
        return None


@contextlib.contextmanager
def call_scope(settings: object, purpose: str) -> Iterator[None]:
    """Make `note_call` record into `settings`' database under `purpose` while the block runs."""
    token = _SCOPE.set((settings, purpose))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def note_call(*, provider: str, model: str, tokens: Tokens | None,
              duration_ms: int | None = None) -> None:
    """Record a call made inside `call_scope`; outside one this does nothing.

    A short-lived engine is opened for the write and closed again, so the judging code needs no
    database handle of its own.
    """
    scope = _SCOPE.get()
    if scope is None:
        return
    settings, purpose = scope
    try:
        from spyglass_service.db import create_db_engine

        engine = create_db_engine(settings.db_path)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- see record_call
        logger.warning("could not open the database to record usage", exc_info=True)
        return
    try:
        record_call(engine, purpose=purpose, provider=provider, model=model, tokens=tokens,
                    duration_ms=duration_ms)
    finally:
        engine.dispose()


def prune_usage(engine, days: int) -> int:
    """Delete rows older than `days` days and return how many were removed.

    The weekly upkeep calls this with 180. Raises ValueError for a limit under one day.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    cutoff = utcnow() - timedelta(days=days)
    ensure_table(engine)
    with Session(engine) as session:
        result = session.execute(delete(UsageCall).where(UsageCall.at < cutoff))  # type: ignore[arg-type]
        session.commit()
        return int(result.rowcount or 0)
