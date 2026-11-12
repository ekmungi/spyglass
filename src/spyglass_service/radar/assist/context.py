"""What the assistant is told: its role, the reader, the item or the day's brief, and the turn.

The system prompt holds everything that stays fixed for a thread (role, reader profile, the item's
text within a budget). The user turn holds the reader's question and any selected passage. Quick
actions are short instruction presets that replace or accompany the typed question.
"""

from sqlalchemy import Engine as DbEngine
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.models import Item
from spyglass_service.radar.assist import feed_context
from spyglass_service.radar.assist.passages import head_of, passages_block
from spyglass_service.radar.models import ItemState, RadarBrief, ReaderDoc, loads
from spyglass_service.radar.profile_defaults import load_profile
from spyglass_service.radar.reader.text import plain_abstract
from spyglass_service.radar.serialize import radar_items

# Characters of article text sent with a thread. About 12k tokens: enough for a long article
# while leaving room for the answer and history on every engine, including small local models.
TEXT_BUDGET = 48_000
# Characters of earlier conversation sent with a new question.
HISTORY_BUDGET = 24_000
# A stored text shorter than this many words is treated as an excerpt, and the feed's own summary
# is added next to it.
SHORT_TEXT_WORDS = 150
# Characters of the feed's own summary sent with an item.
SUMMARY_CHARS = 2_000
# The reader's described projects shown to the assistant: at most this many, and this many
# characters in all (about 1,000 tokens), so a long list cannot crowd out the article.
PROJECTS_MAX = 40
PROJECTS_CHARS = 4_000
PROJECTS_HEADER = "The reader's projects (use these names exactly; never invent a project):"

ROLE = (
    "You are a careful research assistant for one reader. Answer from the text supplied below "
    "first, and say plainly when you go beyond it (for example: 'The article does not say; from "
    "general knowledge ...'). Be short and direct, with no flattery and no filler. When you rely "
    "on a passage, quote it in a few words. If the text does not contain the answer, say so "
    "instead of guessing. Write plain sentences; avoid hype words."
)

ACTIONS: dict[str, str] = {
    "explain": (
        "Explain this in plain language. Say what it is, how it works or what happened, and the "
        "one thing to take away. Define any term a smart non-specialist would not know."),
    "relevance": (
        "How does this connect to my stated field and topics? Say what it changes or confirms for "
        "me, and what I could do with it (a decision, a thing to try, someone to tell). If it is "
        "not relevant, say so in one sentence."),
    "colleagues": (
        "Draft a short message I can paste to colleagues: what happened, why it matters to our "
        "work, and the link. Plain words, three or four sentences, no greeting fluff."),
    "linkedin": (
        "Draft a LinkedIn post in the first person: concrete, specific to what this says, no hype "
        "words, no pile of hashtags, no em dashes. About 120 to 180 words. End with the link."),
    "blog": (
        "Outline a blog post about this: a working title, the argument in one sentence, four to "
        "six section headings with one line each saying what the section does, and the sources "
        "to cite."),
    "projects": (
        "Say which of the reader's projects this item could help, if any, and as what: a "
        "resource, something to explore, a learning, or a feature idea. Give one or two sentences "
        "of reasoning per project, quoting the passage you rely on. If none fits, say so plainly. "
        "Never invent a project and never propose more than three. If the system prompt has no "
        "block listing the reader's projects, answer only that no projects have been described "
        "yet and that they can be added on the Profile page."),
    # Presets for a conversation about the whole feed (see `feed_context`).
    **feed_context.ACTIONS,
}


def action_names() -> list[str]:
    """The preset names the API accepts."""
    return list(ACTIONS)


def render_brief(doc: dict) -> str:
    """The brief document as plain text: opening, then each section's headlines and whys."""
    lines = [f"Daily brief for {doc.get('day', '')}", str(doc.get("opening") or "")]
    for section in doc.get("sections") or []:
        lines.append(f"\n{section.get('title', '')}")
        for story in section.get("stories") or []:
            names = ", ".join(s.get("name", "") for s in story.get("sources") or [] if s.get("name"))
            lines.append(f"- {story.get('headline', '')}: {story.get('why') or ''}"
                         + (f" ({names})" if names else ""))
    return "\n".join(line for line in lines if line is not None).strip()


# What the assistant is told about the text it has, by kind (see `text_kind`).
_TEXT_STATUS = {
    "full": "Text supplied: the full article text.",
    "preview": ("Text supplied: only a PREVIEW of the article. The site limits the full article to "
                "subscribers, so the rest exists but is not available here. Say that you have only a preview."),
    "short": ("Text supplied: a short stored text that may be only an excerpt or an abstract, not the whole "
              "article. Say so when the question needs more than it gives."),
    "summary": ("Text supplied: none. No article text is stored; all you have is the feed's own summary and "
                "key points. When asked for more than they say, answer that you only have the summary."),
    "none": "Text supplied: none. No article text and no summary are stored; only the details above are known.",
}


def text_kind(words: int, has_summary: bool, reader_status: str | None) -> str:
    """What kind of text an item has: "full", "preview" (paywalled), "short" (an excerpt),
    "summary" (only the feed's own summary) or "none"."""
    if words == 0:
        return "summary" if has_summary else "none"
    if reader_status == "partial":
        return "preview"
    return "short" if words < SHORT_TEXT_WORDS else "full"


def _item_block(db: DbEngine, session: Session, item_id: int) -> str:
    """The item's title, source, date, link, key points, the reader's note and its text.

    The text depends only on the item, never on the question or the selected passage, so the
    system prompt is the same on every turn and can be read from the provider's cache.
    """
    found = radar_items(session, [item_id])
    if not found:
        return "(The item this conversation was opened on no longer exists.)"
    item = found[0]
    state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
    head = [
        f"Title: {item['title']}",
        f"Publication: {item.get('origin') or 'unknown'}",
        f"Published: {item.get('published_at') or 'unknown'}",
        f"URL: {item['url']}",
    ]
    if item.get("key_points"):
        head.append("Key points:\n" + "\n".join(f"- {p}" for p in item["key_points"]))
    if item.get("why"):
        head.append(f"Why it may matter to the reader: {item['why']}")
    if state and state.user_note:
        head.append(f"The reader's own note on it: {state.user_note}")
    stored = content_store.get_fulltext(db, item_id)
    body = (stored or {}).get("markdown") or ""
    record = session.get(Item, item_id)
    summary = plain_abstract(record.summary if record else None)[:SUMMARY_CHARS]
    reader = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first()
    kind = text_kind(len(body.split()), bool(summary), reader.status if reader else None)
    if summary and kind != "full":
        head.append(f"Summary from the feed: {summary}")
    head.append(_TEXT_STATUS[kind])
    if not body:
        return "\n".join(head) + "\n\n(No full text is stored for this item; only the details above are known.)"
    shown = head_of(body, TEXT_BUDGET) if len(body) > TEXT_BUDGET else body
    if len(shown) < len(body):
        head.append(f"The text below is the beginning of the article: {len(shown):,} of {len(body):,} "
                    "characters. The rest is not in these instructions; when a conversation starts, "
                    "passages from it that are closest to the reader's question are added to the "
                    "reader's message and are marked as selected passages. Do not say that a section or "
                    "a topic is missing from the document just because it is not in the shown parts.")
    label = "Full text" if kind == "full" else "Stored text"
    return "\n".join(head) + f"\n\n{label}:\n" + shown


def long_item_passages(db: DbEngine, item_id: int, question: str, index_provider=None) -> str:
    """The passages to add to the question about an article longer than the text budget, or "".

    They come from the part of the article that the system prompt does not hold and are chosen by
    their similarity to `question`. `index_provider` returns the embedding index; without one, or
    when it fails, passages are chosen by the words they share with the question.
    """
    body = ((content_store.get_fulltext(db, item_id) or {}).get("markdown")) or ""
    if len(body) <= TEXT_BUDGET:
        return ""
    index = None
    if index_provider is not None:
        try:
            index = index_provider()
        except Exception:  # noqa: BLE001 -- the index is optional here
            index = None
    shown = len(head_of(body, TEXT_BUDGET))
    return passages_block(body, shown, question, TEXT_BUDGET - shown, index)


def projects_block(session: Session) -> str:
    """The reader's described projects as a prompt block, or "" when there are none.

    One line per project, `- name: description`, at most `PROJECTS_MAX` projects and
    `PROJECTS_CHARS` characters. The list comes from `radar.projects.described_projects`, which
    returns only projects the reader has described; a missing module counts as no projects.
    """
    try:
        from spyglass_service.radar.projects import described_projects
    except ImportError:
        return ""
    lines: list[str] = []
    used = 0
    for entry in described_projects(session)[:PROJECTS_MAX]:
        name = " ".join(str(entry.get("name") or "").split())
        description = " ".join(str(entry.get("description") or "").split())
        if not name or not description:
            continue
        line = f"- {name}: {description}"
        if used + len(line) + 1 > PROJECTS_CHARS:
            line = line[: max(0, PROJECTS_CHARS - used - 1)].rstrip()
            if len(line) > len(name) + 4:
                lines.append(line)
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    return PROJECTS_HEADER + "\n" + "\n".join(lines)


def build_system(db: DbEngine, *, item_id: int | None = None, brief_day: str | None = None,
                 selection: str | None = None, feed_block: str | None = None) -> str:
    """The system prompt for a thread on an item, on a day's brief, or on the feed.

    `feed_block` is the retrieved-items text from `feed_context.build_feed_block`; it is used
    only for a thread with neither an item nor a day, and the rules for answering from it come
    first, outside the privacy fence. `selection` is accepted for callers that pass it but no
    longer changes the prompt: the text must not depend on the question (see `_item_block`).
    """
    with Session(db) as session:
        profile = load_profile(session)
        topics = "; ".join(t.get("name", "") for t in profile.get("topics", []) if t.get("name"))
        parts = [ROLE, f"About the reader: {profile.get('statement', '')}"]
        if topics:
            parts.append(f"Topics the reader follows: {topics}.")
        projects = projects_block(session)
        if projects:
            parts.append(projects)
        if item_id is not None:
            parts.append("=== THE ITEM ===\n" + _item_block(db, session, item_id))
        elif brief_day:
            row = session.exec(select(RadarBrief).where(RadarBrief.day == brief_day)).first()
            doc = loads(row.doc if row else None, None)
            parts.append("=== THE DAY'S BRIEF ===\n"
                         + (render_brief(doc) if isinstance(doc, dict) else "(No brief for that day.)"))
        elif feed_block is not None:
            parts.extend([feed_context.INSTRUCTIONS, feed_block])
    return "\n\n".join(parts)


def build_turn(content: str, selection: str | None = None, action: str | None = None) -> str:
    """The reader's turn: selected passage as a quoted block, then the preset and/or the question."""
    parts: list[str] = []
    if selection and selection.strip():
        quoted = "\n".join(f"> {line}" for line in selection.strip().splitlines())
        parts.append("The reader selected this passage:\n" + quoted)
    instruction = ACTIONS.get(action or "")
    typed = (content or "").strip()
    if instruction and typed:
        parts.append(f"{instruction}\nExtra from the reader: {typed}")
    elif instruction:
        parts.append(instruction)
    elif typed:
        parts.append(typed)
    return "\n\n".join(parts)


def trim_history(messages: list[dict], budget: int = HISTORY_BUDGET) -> list[dict]:
    """Keep the newest messages that fit `budget` characters; the last message is always kept
    and the result never starts with an assistant message (some APIs reject that)."""
    kept: list[dict] = []
    used = 0
    for message in reversed(messages):
        size = len(message.get("content", ""))
        if kept and used + size > budget:
            break
        kept.append(message)
        used += size
    kept.reverse()
    while len(kept) > 1 and kept[0]["role"] != "user":
        kept.pop(0)
    return kept
