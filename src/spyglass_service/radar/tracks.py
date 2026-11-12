"""Tracks: subjects the reader follows ("Capsule endoscopy AI"), stored as one JSON document.

A track has a label (what the reader sees), a precise news-search query, a profile section and a
kind. Following a track also adds its label to the profile's topics, so the relevance judge
favours it, and runs its search once right away. Every collection cycle runs the active tracks'
queries beside the profile topics' own.

All writes are read-modify-write on the single RadarDoc row "tracks" under one module-level
lock, so two requests cannot lose each other's change.
"""

import logging
import re
import threading

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.models import ItemExtra, RadarDoc, dumps, loads, utcnow
from spyglass_service.radar.profile import ProfileError, get_profile, save_profile, section_keys
from spyglass_service.radar.profile_defaults import load_profile, section_label

logger = logging.getLogger(__name__)

TRACKS_KEY = "tracks"
KINDS = ("topic", "organisation", "person", "product")
# Longest label and query accepted. The profile topic limit (200) is the looser bound.
MAX_LABEL = 80
MAX_QUERY = 200
# One collection cycle runs at most this many queries in total (tracks first, then topics).
MAX_CYCLE_QUERIES = 40
# How far back the search made at the moment of following looks, in days.
FOLLOW_LOOKBACK_DAYS = 7

_LOCK = threading.RLock()
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_NOT_WORD = re.compile(r"[^\w]+")


class TrackError(ValueError):
    """The track data is not acceptable; the message is fit to show the reader."""


class TrackConflict(TrackError):
    """Another track already has this label."""


class TrackNotFound(LookupError):
    """No track has this id."""


def norm_label(label: str) -> str:
    """Case- and punctuation-insensitive form of a label, used to spot duplicates."""
    return _NOT_WORD.sub(" ", label.casefold()).strip()


def clean_text(value: object, limit: int, name: str) -> str:
    """A trimmed single-line string within `limit`, or TrackError saying what is wrong."""
    if not isinstance(value, str):
        raise TrackError(f"{name} must be text")
    if _CONTROL.search(value):
        raise TrackError(f"{name} contains control characters")
    text = " ".join(value.split())
    if not text:
        raise TrackError(f"{name} is required")
    if len(text) > limit:
        raise TrackError(f"{name} is too long (at most {limit} characters)")
    return text


def _read(session: Session) -> dict:
    """The stored document as {"next_id": int, "tracks": [dict]}."""
    row = session.get(RadarDoc, TRACKS_KEY)
    doc = loads(row.body if row else None, None)
    if not isinstance(doc, dict) or not isinstance(doc.get("tracks"), list):
        return {"next_id": 1, "tracks": []}
    tracks = [t for t in doc["tracks"] if isinstance(t, dict) and isinstance(t.get("id"), int)]
    next_id = max([int(doc.get("next_id") or 1)] + [t["id"] + 1 for t in tracks])
    return {"next_id": next_id, "tracks": tracks}


def _write(session: Session, doc: dict) -> None:
    """Store the document (caller holds the lock)."""
    row = session.get(RadarDoc, TRACKS_KEY)
    if row is None:
        row = RadarDoc(key=TRACKS_KEY, body=dumps(doc))
    else:
        row.body = dumps(doc)
        row.updated_at = utcnow()
    session.add(row)
    session.commit()


def list_tracks(engine: Engine) -> list[dict]:
    """Every track, newest first, as stored (copies the caller may keep)."""
    with Session(engine) as session:
        tracks = _read(session)["tracks"]
    return sorted((dict(t) for t in tracks), key=lambda t: t["id"], reverse=True)


def get_track(engine: Engine, track_id: int) -> dict:
    """One track by id; raises TrackNotFound."""
    for track in list_tracks(engine):
        if track["id"] == track_id:
            return track
    raise TrackNotFound(f"track {track_id} not found")


def followed_names(session: Session) -> tuple[set[str], set[str]]:
    """(normalised labels of tracks, normalised names of profile topics) used for duplicates."""
    labels = {norm_label(str(t.get("label", ""))) for t in _read(session)["tracks"]}
    topics = {norm_label(str(t.get("name", ""))) for t in load_profile(session).get("topics", [])}
    return labels, topics


def followed_queries(session: Session) -> set[str]:
    """Lower-cased queries of the existing tracks."""
    return {str(t.get("query", "")).casefold() for t in _read(session)["tracks"]}


def validate_section(session: Session, section: str) -> str:
    """The section key if the profile defines it, else TrackError."""
    keys = section_keys(load_profile(session))
    if section not in keys:
        raise TrackError(f"unknown section {section!r}; use one of: {', '.join(keys)}")
    return section


def _topic_index(profile: dict, label: str) -> int | None:
    """Position of the profile topic whose name matches `label`, or None."""
    wanted = norm_label(label)
    for index, topic in enumerate(profile.get("topics", [])):
        if norm_label(str(topic.get("name", ""))) == wanted:
            return index
    return None


def _add_topic(session: Session, label: str, section: str) -> bool:
    """Add `label` to the profile topics unless present; True when this call added it."""
    profile = get_profile(session)
    if _topic_index(profile, label) is not None:
        return False
    profile["topics"] = [*profile.get("topics", []), {"name": label, "section": section}]
    try:
        save_profile(session, profile)
    except ProfileError:
        logger.warning("could not add %r to the profile topics", label, exc_info=True)
        return False
    return True


def _drop_topic(session: Session, label: str) -> None:
    """Remove the profile topic named `label`, when it is still there."""
    profile = get_profile(session)
    index = _topic_index(profile, label)
    if index is None:
        return
    profile["topics"] = [t for i, t in enumerate(profile["topics"]) if i != index]
    try:
        save_profile(session, profile)
    except ProfileError:
        logger.warning("could not remove %r from the profile topics", label, exc_info=True)


def _rename_topic(session: Session, old: str, new: str, section: str) -> None:
    """Rename (and move) the profile topic that a track added."""
    profile = get_profile(session)
    index = _topic_index(profile, old)
    if index is None or (norm_label(old) != norm_label(new) and _topic_index(profile, new) is not None):
        return
    topics = list(profile["topics"])
    topics[index] = {"name": new, "section": section}
    profile["topics"] = topics
    try:
        save_profile(session, profile)
    except ProfileError:
        logger.warning("could not rename topic %r", old, exc_info=True)


def create_track(
    engine: Engine, *, label: str, query: str, section: str, kind: str,
    from_item_id: int | None = None,
) -> dict:
    """Store a new track and add its label to the profile topics.

    Raises TrackError for bad input and TrackConflict when a track has the same normalised
    label. Does not search; see `run_track_now`.
    """
    label = clean_text(label, MAX_LABEL, "label")
    query = clean_text(query, MAX_QUERY, "query")
    if kind not in KINDS:
        raise TrackError(f"kind must be one of: {', '.join(KINDS)}")
    with _LOCK, Session(engine) as session:
        validate_section(session, section)
        doc = _read(session)
        if any(norm_label(str(t.get("label", ""))) == norm_label(label) for t in doc["tracks"]):
            raise TrackConflict("You already follow a track with this name.")
        track = {
            "id": doc["next_id"], "label": label, "query": query, "section": section,
            "kind": kind, "active": True, "created_at": utcnow().isoformat(),
            "from_item_id": from_item_id, "last_run_at": None, "last_new": 0,
            "topic_added": _add_topic(session, label, section),
        }
        _write(session, {"next_id": doc["next_id"] + 1, "tracks": [*doc["tracks"], track]})
        return dict(track)


def update_track(engine: Engine, track_id: int, changes: dict) -> dict:
    """Apply label, query, section and/or active changes; returns the updated track."""
    with _LOCK, Session(engine) as session:
        doc = _read(session)
        current = next((t for t in doc["tracks"] if t["id"] == track_id), None)
        if current is None:
            raise TrackNotFound(f"track {track_id} not found")
        updated = dict(current)
        if "label" in changes:
            updated["label"] = clean_text(changes["label"], MAX_LABEL, "label")
            clash = any(
                t["id"] != track_id and norm_label(str(t.get("label", ""))) == norm_label(updated["label"])
                for t in doc["tracks"]
            )
            if clash:
                raise TrackConflict("You already follow a track with this name.")
        if "query" in changes:
            updated["query"] = clean_text(changes["query"], MAX_QUERY, "query")
        if "section" in changes:
            updated["section"] = validate_section(session, changes["section"])
        if "active" in changes:
            updated["active"] = bool(changes["active"])
        if updated.get("topic_added") and (
            updated["label"] != current["label"] or updated["section"] != current["section"]
        ):
            _rename_topic(session, current["label"], updated["label"], updated["section"])
        tracks = [updated if t["id"] == track_id else t for t in doc["tracks"]]
        _write(session, {"next_id": doc["next_id"], "tracks": tracks})
        return dict(updated)


def delete_track(engine: Engine, track_id: int) -> None:
    """Remove a track; its profile topic goes too, but only if the track added that topic."""
    with _LOCK, Session(engine) as session:
        doc = _read(session)
        current = next((t for t in doc["tracks"] if t["id"] == track_id), None)
        if current is None:
            raise TrackNotFound(f"track {track_id} not found")
        if current.get("topic_added"):
            _drop_topic(session, str(current["label"]))
        _write(session, {
            "next_id": doc["next_id"],
            "tracks": [t for t in doc["tracks"] if t["id"] != track_id],
        })


def active_queries(engine: Engine) -> list[str]:
    """Queries of the active tracks, newest track first."""
    return [t["query"] for t in list_tracks(engine) if t.get("active") and t.get("query")]


def merge_queries(track_queries: list[str], topic_queries: list[str],
                  cap: int = MAX_CYCLE_QUERIES) -> list[str]:
    """Tracks' queries first, then the topics', without repeats (ignoring case), at most `cap`."""
    seen: set[str] = set()
    merged: list[str] = []
    for query in [*track_queries, *topic_queries]:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            merged.append(query)
    return merged[:cap]


def record_runs(engine: Engine, ran: set[str], new_by_query: dict[str, int]) -> None:
    """Note on each track whose query was run: when, and how many new items it brought.

    Never raises: bookkeeping must not fail a collection.
    """
    if not ran:
        return
    try:
        with _LOCK, Session(engine) as session:
            doc = _read(session)
            now = utcnow().isoformat()
            tracks = [
                {**t, "last_run_at": now, "last_new": int(new_by_query.get(t["query"], 0))}
                if t.get("query") in ran else t
                for t in doc["tracks"]
            ]
            if tracks != doc["tracks"]:
                _write(session, {"next_id": doc["next_id"], "tracks": tracks})
    except Exception:  # noqa: BLE001 -- bookkeeping only
        logger.exception("could not record track runs")


def run_track_now(engine: Engine, settings, track: dict, *, fetch=None, decode=None) -> int:
    """Search the track's query once, store the results and make cards; returns new items.

    A failing search is logged and counts as zero, so it can never fail the follow.
    """
    from spyglass_service.cards import materialize_cards
    from spyglass_service.radar.sources.news_search import collect_news

    try:
        new = collect_news(engine, settings, queries=[track["query"]], days=FOLLOW_LOOKBACK_DAYS,
                           pause=0, fetch=fetch, decode=decode)
        materialize_cards(engine)
    except Exception:  # noqa: BLE001 -- the follow itself already succeeded
        logger.exception("immediate search for track %r failed", track.get("label"))
        return 0
    record_runs(engine, {track["query"]}, {track["query"]: new})
    return new


def recent_item_ids(session: Session, query: str, limit: int = 3) -> list[int]:
    """Ids of the newest items found by `query` (the news collector stores it in ItemExtra)."""
    rows = session.exec(
        select(Item.id)
        .join(ItemExtra, ItemExtra.item_id == Item.id)
        .where(func.json_extract(ItemExtra.data, "$.query") == query)
        .order_by(func.coalesce(Item.published_at, Item.fetched_at).desc(), Item.id.desc())
        .limit(limit)
    ).all()
    return list(rows)


def with_section_label(session: Session, track: dict) -> dict:
    """The track plus its section's display label."""
    return {**track, "section_label": section_label(session, track["section"])}
