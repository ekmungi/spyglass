"""Spyglass items as Claude sees them: by code, by @ reference, and in the linked session.

Every item has a short code, `#<card id>`. `get_item` resolves a code, and the items the user is
most likely to mean (what is open or ticked, the latest brief, the papers shared lately, the most
recently touched cards) are listed as MCP resources, `spyglass://item/<id>`, so they appear when
the user types @ in the Claude desktop Code tab. Reading one returns a short markdown card.
"""

import logging
import re

import anyio
from fastmcp import Context, FastMCP
from fastmcp.resources import TextResource
from fastmcp.server.middleware import Middleware
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.claude_link import card_titles, short_title
from spyglass_service.linked_session import LINK_TOOL, SESSION_GUIDE
from spyglass_service.detail_notes import folder_names
from spyglass_service.job_prompts import instructions
from spyglass_service.models import Brief, Card, CardState, Content, InboxEntry, Item

logger = logging.getLogger(__name__)

URI_PREFIX = "spyglass://item/"
# How many items the @ list offers: enough to find today's work, short enough to scan.
LISTED = 60
_CODE = re.compile(r"^\s*#?\s*(\d+)\s*$")


# SQLite integers are 64-bit; a larger "code" is simply not an item.
_MAX_ID = 2**63 - 1


def parse_code(code: int | str) -> int | None:
    """The card id in an item code: 1042, "1042" or "#1042"; None for anything else."""
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        value = code
    else:
        match = _CODE.match(str(code))
        if not match:
            return None
        value = int(match.group(1))
    return value if 0 < value <= _MAX_ID else None


def item_view(engine: Engine, card_id: int) -> dict | None:
    """What Claude needs to act on one item, or None when there is no such card."""
    with Session(engine) as session:
        card = session.get(Card, card_id)
        item = session.get(Item, card.item_id) if card else None
        if card is None or item is None:
            return None
        has_text = session.exec(select(Content.id).where(Content.item_id == item.id)).first()
        return {
            "card_id": card.id,
            "code": f"#{card.id}",
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "origin": item.origin,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": card.summary or "",
            "state": card.state.value if isinstance(card.state, CardState) else card.state,
            "category": card.category,
            "relevance": card.relevance,
            "feedback": card.feedback,
            "note_path": card.briefing_path,
            "has_fulltext": has_text is not None,
        }


def item_markdown(view: dict) -> str:
    """The card a resource read returns: data about the item, not instructions."""
    lines = [f"# {view['code']} {view['title']}", "", f"- Source: {view['origin'] or view['source']}"]
    lines.append(f"- Link: {view['url']}")
    if view["note_path"]:
        lines.append(f"- Vault note: {view['note_path']}")
    lines.append(f"- Full text stored: {'yes' if view['has_fulltext'] else 'no'}")
    if view["summary"]:
        lines += ["", view["summary"]]
    return "\n".join(lines)


def listed_ids(engine: Engine, first: list[int], limit: int = LISTED) -> list[int]:
    """Card ids for the @ list: `first` (open and ticked), then the latest brief, recent shares,
    and the most recently updated cards that are not archived, without repeats."""
    with Session(engine) as session:
        brief = session.exec(select(Brief.id).order_by(Brief.created_at.desc())).first()  # type: ignore[union-attr]
        in_brief = (
            session.exec(select(Card.id).where(Card.brief_id == brief)).all() if brief else []
        )
        shared = session.exec(
            select(InboxEntry.card_id).order_by(InboxEntry.added_at.desc()).limit(limit)  # type: ignore[union-attr]
        ).all()
        recent = session.exec(
            select(Card.id)
            .where(Card.state != CardState.DISMISSED)
            .order_by(Card.updated_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        ).all()
    seen: list[int] = []
    for card_id in [*first, *in_brief, *shared, *recent]:
        if card_id is not None and card_id not in seen:
            seen.append(card_id)
    return seen[:limit]


class ItemResources(Middleware):
    """Add the likely items to resources/list, so @ offers them by code and title."""

    def __init__(self, state) -> None:
        self.state = state

    async def on_list_resources(self, context, call_next):
        listed = list(await call_next(context))
        first = [i for i in [self.state.open_card_id, *self.state.selection] if i is not None]
        try:
            # Database work runs in a worker thread so it never stalls the MCP server.
            titles = await anyio.to_thread.run_sync(self._titles, first)
        except Exception:  # noqa: BLE001 -- the @ list is a convenience; never fail the listing
            logger.warning("Could not list Spyglass items for @", exc_info=True)
            return listed
        for card_id, title in titles:
            listed.append(
                TextResource(
                    uri=f"{URI_PREFIX}{card_id}",
                    name=f"#{card_id} {short_title(title)}",
                    description="A Spyglass item",
                    text="",
                    mime_type="text/markdown",
                )
            )
        return listed

    def _titles(self, first: list[int]) -> list[tuple[int, str]]:
        return card_titles(self.state.engine, listed_ids(self.state.engine, first))


def register_item_tools(mcp: FastMCP, state) -> None:
    """The linked-session tools, the item resources and the instructions Spyglass serves."""

    @mcp.resource(URI_PREFIX + "{card_id}", mime_type="text/markdown")
    def item_resource(card_id: int) -> str:
        """One Spyglass item, as picked with @."""
        view = item_view(state.engine, card_id)
        return item_markdown(view) if view else f"No Spyglass item #{card_id}."

    @mcp.tool(name=LINK_TOOL)
    def link_session(code: str, ctx: Context) -> dict:
        """Claim the link to Spyglass with the code in this session's first message. The newest
        claim wins; earlier linked sessions are refused from then on. Returns the instructions
        for the linked session."""
        if not state.link.claim(code, ctx.session_id):
            return {"linked": False, "error": "unknown_code",
                    "detail": "The code is unknown or expired. Open a new linked session from "
                              "Spyglass."}
        return {"linked": True, "instructions": SESSION_GUIDE}

    @mcp.tool
    def get_item(code: str | int) -> dict:
        """One item by its code ("#1042" or 1042): title, link, source, summary, state, vault
        note path and whether its full text is stored."""
        card_id = parse_code(code)
        view = item_view(state.engine, card_id) if card_id is not None else None
        return view or {"error": "not_found", "detail": f"No Spyglass item {code!r}"}

    @mcp.tool
    def set_item_note(code: str | int, note_path: str) -> dict:
        """Record where an item's vault note is now, after you moved it: the item's code and the
        note's vault-relative path (for example "02 AREAS/Imaging/Primer.md")."""
        card_id = parse_code(code)
        vault = state.settings.vault_path
        if card_id is None or item_view(state.engine, card_id) is None:
            return {"error": "not_found", "detail": f"No Spyglass item {code!r}"}
        if vault is None:
            return {"error": "no_vault", "detail": "Spyglass has no vault folder set."}
        cleaned = note_path.strip().replace("\\", "/").lstrip("/")
        target = vault / cleaned
        if target.suffix.lower() != ".md":
            target = target.with_name(target.name + ".md")
        try:
            target.resolve().relative_to(vault.resolve())
        except ValueError:
            return {"error": "outside_vault", "detail": f"{note_path} is not inside the vault."}
        if not target.is_file():
            return {"error": "no_note", "detail": f"There is no note at {note_path}."}
        with Session(state.engine) as session:
            card = session.get(Card, card_id)
            card.briefing_path = str(target)
            session.add(card)
            session.commit()
        return {"recorded": True, "note_path": target.relative_to(vault).as_posix()}

    @mcp.tool
    def get_instructions(job: str) -> dict:
        """Instructions Spyglass serves for a job, so any engine can follow them. Jobs:
        "linked-session", "inbox" (its run-specific steps come from inbox_start), and the
        background jobs "prepare-detail" and "file-note" (their runs get them from job_start)."""
        if job == "linked-session":
            return {"job": job, "instructions": SESSION_GUIDE}
        if job == "inbox":
            return {"job": job, "instructions": "Call inbox_start; it returns the run's "
                                                "instructions."}
        if job in ("prepare-detail", "file-note"):
            settings = state.settings
            return {"job": job, "instructions": instructions(
                job, spyglass_folders=folder_names(settings))}
        return {"error": "unknown_job",
                "jobs": ["linked-session", "inbox", "prepare-detail", "file-note"]}
