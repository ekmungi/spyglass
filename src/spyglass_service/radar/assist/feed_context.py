"""What the assistant is told in a conversation about the whole feed.

For every turn the items closest to the reader's question are retrieved (`radar.feed_search`) and
listed after the marker `=== THE FEED ===`. The privacy layer fences everything after that marker
as material, so the instructions that tell the model how to answer sit before it, outside the
fence. The model must cite items with the marker `[#<id>]`; the interface turns those markers into
links to the items.
"""

from datetime import UTC, datetime

from sqlalchemy import Engine as DbEngine
from sqlmodel import Session

from spyglass_service.radar import feed_search
from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow
from spyglass_service.radar.serialize import radar_items

# The line after which the privacy layer fences the text (see `radar.privacy`).
FEED_MARKER = "=== THE FEED ==="
# Most items put in one turn, and the cap on the whole list in characters (about 6k tokens).
FEED_ITEMS_MAX = 25
FEED_BLOCK_CHARS = 24_000
# Key points shown per item, and the longest piece of each text field.
KEY_POINTS_PER_ITEM = 2
_HEADLINE_CHARS = 200
_WHY_CHARS = 400
_POINT_CHARS = 300
# A feed conversation remembers the ids it has retrieved, so the interface can show headlines for
# the citations of earlier answers; the list is kept in a small stored document per thread.
_REMEMBER_KEY = "assist_feed:{thread_id}"
_REMEMBER_MAX = 300
# Days a "this week" preset looks back.
WEEK_DAYS = 7
EMPTY_NOTE = "No items in the feed are close to this question."

INSTRUCTIONS = (
    "This conversation is about the reader's whole feed, not about one article. For each "
    "question the items closest to it are retrieved and listed under the heading THE FEED. For "
    "this conversation these rules replace the general rule about going beyond the supplied "
    "text. Answer only from the listed items. Cite every claim with the marker of the item it "
    "comes from, in the exact form [#123] with the item's own id, written right after the claim; "
    "write one id per bracket, as [#12] [#40], never [#12, #40]. When several items bear on the "
    "question, group the answer by theme with a short plain heading for each theme. If the list "
    "says that no item is close to the question, say plainly that the feed has nothing on it and "
    "stop; do not answer from general knowledge. Never invent an item, an id or a link, and cite "
    "only ids that appear in the list."
)

# Quick-action presets for a feed conversation, and the number of days of feed they draw on.
ACTIONS: dict[str, str] = {
    "feed_week": ("What matters most in my feed from the last 7 days? Five items at most, each "
                  "with one sentence on why."),
    "feed_themes": ("Which themes run through my feed this week? Name each theme and cite its "
                    "items."),
}


def retrieval_query(question: str, selection: str | None = None) -> str:
    """The text used to find related items: the question plus the quoted selection, if any."""
    parts = [(question or "").strip(), (selection or "").strip()]
    return "\n".join(p for p in parts if p)


def _clip(text: object, size: int) -> str:
    """One line of `text`, at most `size` characters."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= size else flat[: size - 1].rstrip() + "…"


def render_item(item: dict) -> str:
    """One retrieved item as a few lines that start with its citation marker."""
    day = str(item.get("published_at") or item.get("fetched_at") or "")[:10] or "unknown date"
    head = f"[#{item['id']}] {_clip(item.get('headline') or item.get('title'), _HEADLINE_CHARS)}"
    meta = (f"  {item.get('origin') or 'unknown publication'} | {day} | "
            f"{item.get('section_label') or 'no section'} | tier {item.get('tier') or 'unjudged'}")
    lines = [head, meta]
    if item.get("why"):
        lines.append(f"  Why it matters: {_clip(item['why'], _WHY_CHARS)}")
    lines += [f"  - {_clip(p, _POINT_CHARS)}"
              for p in (item.get("key_points") or [])[:KEY_POINTS_PER_ITEM]]
    return "\n".join(lines)


def find_items(session: Session, index, *, question: str, selection: str | None,
               action: str | None) -> list[int]:
    """Ids of the items to show for this turn, best first.

    A "this week" preset takes the strongest recent items; any other turn takes the items
    closest to the question (and the selected passage).
    """
    if action in ACTIONS:
        found = feed_search.recent_items(session, days=WEEK_DAYS, limit=FEED_ITEMS_MAX)
    else:
        found = feed_search.related_items(
            session, index, retrieval_query(question, selection), limit=FEED_ITEMS_MAX)
    return [item_id for item_id, _ in found]


def build_feed_block(db: DbEngine, index, *, question: str, selection: str | None = None,
                     action: str | None = None) -> tuple[str, list[int]]:
    """The text after the feed marker for this turn, and the ids of the items it lists.

    The list stops before it would pass `FEED_BLOCK_CHARS` characters. With nothing close to the
    question the block says so, which the instructions tell the model to repeat to the reader.
    """
    today = datetime.now(UTC).date().isoformat()
    with Session(db) as session:
        ids = find_items(session, index, question=question, selection=selection, action=action)
        items = radar_items(session, ids)
    header = f"{FEED_MARKER}\nToday is {today}."
    if not items:
        return f"{header}\n{EMPTY_NOTE}", []
    parts = [f"{header}\nThe {len(items)} closest items, best first:"]
    used = len(parts[0])
    shown: list[int] = []
    for item in items:
        entry = render_item(item)
        if used + len(entry) + 2 > FEED_BLOCK_CHARS:
            break
        parts.append(entry)
        used += len(entry) + 2
        shown.append(item["id"])
    return "\n\n".join(parts), shown


def headlines(db: DbEngine, ids: list[int]) -> list[dict]:
    """[{"id", "headline"}] for the given ids, in order; ids that no longer exist are skipped."""
    with Session(db) as session:
        return [{"id": i["id"], "headline": i["headline"]} for i in radar_items(session, ids)]


def remember_retrieved(db: DbEngine, thread_id: int, ids: list[int]) -> None:
    """Add `ids` to the thread's remembered set (newest last, at most `_REMEMBER_MAX`)."""
    if not ids:
        return
    key = _REMEMBER_KEY.format(thread_id=thread_id)
    with Session(db) as session:
        row = session.get(RadarDoc, key)
        known = [i for i in loads(row.body if row else None, []) if isinstance(i, int)]
        merged = [*(i for i in known if i not in ids), *ids][-_REMEMBER_MAX:]
        if row is None:
            session.add(RadarDoc(key=key, body=dumps(merged)))
        else:
            row.body, row.updated_at = dumps(merged), utcnow()
            session.add(row)
        session.commit()


def thread_retrieved(db: DbEngine, thread_id: int) -> list[dict]:
    """The headlines of every item the thread has retrieved so far."""
    with Session(db) as session:
        row = session.get(RadarDoc, _REMEMBER_KEY.format(thread_id=thread_id))
        ids = [i for i in loads(row.body if row else None, []) if isinstance(i, int)]
    return headlines(db, ids)
