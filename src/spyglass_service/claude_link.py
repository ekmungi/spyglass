"""Opening a Claude Code desktop session from the dashboard.

Every Claude action in Spyglass opens a new session in the Code tab of the Claude desktop app
with a `claude://code/new` link: the prompt is typed in for the user to send, and the vault is the
session's folder, so the session sees the vault's `.mcp.json` (the spyglass MCP server) and
skills. Nothing runs in a terminal. A prompt too long for a link is kept as a hand-off that the
session fetches with the `get_handoff` MCP tool.
"""

import itertools
import os
import re
import secrets
import sys
import threading
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Card, Item

# The dashboard's general Claude entry point: the spyglass skill owns the session menu,
# so the prompt only points at it.
DEFAULT_PROMPT = "Use the spyglass skill and start with its session menu."

# Longest link handed to the operating system. The desktop app truncates its prompt near
# 14,000 characters, but Windows may cut a URL handed to its shell much earlier, so links stay
# short and longer prompts travel as hand-offs.
LINK_MAX = 2000

TITLE_MAX = 80
HANDOFF_TTL = timedelta(hours=24)

LinkOpener = Callable[[str], None]


# A Claude desktop bug (anthropics/claude-code issues 92210 and 98285, open on 2026-10-15): when a
# link's folder text is the same as the folder already selected in Claude, Claude skips adopting
# it. The folder chip still shows the vault, but the session starts in an empty scratch folder.
# Spyglass therefore alternates two spellings of the same Windows path that a folder picker
# never produces ("C:/..." and "c:/..."), so each link's folder text differs from the previous
# link's and from a folder picked by hand. Other systems get the path as it is.
_folder_turns = itertools.count()
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def folder_text(folder: Path | str, turn: int) -> str:
    """The folder as a link carries it: a Windows path in forward slashes, its drive letter in
    upper case on even turns and lower case on odd ones."""
    text = str(folder)
    if not _DRIVE_PATH.match(text):
        return text
    posix = text.replace("\\", "/")
    drive = posix[0].upper() if turn % 2 == 0 else posix[0].lower()
    return drive + posix[1:]


def desktop_link(prompt: str, folder: Path | str) -> str:
    """The claude:// link that opens a new Code-tab session in `folder` with `prompt` typed in."""
    return f"claude://code/new?q={quote(prompt, safe='')}&folder={quote(str(folder), safe='')}"


def default_opener(url: str) -> None:
    """Hand the link to the operating system, which opens the Claude desktop app. Raises when
    nothing could open it, so the dashboard can offer to copy the prompt instead."""
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606 -- a registered protocol
    elif not webbrowser.open(url):
        raise OSError(f"no application opened {url.split('?', 1)[0]}")


def short_title(title: str) -> str:
    """A title as data for the prompt: one line, no quotes, at most TITLE_MAX characters. Titles
    come from feeds and Slack, so they must not be able to read as instructions or break out of
    the quotes they are shown in."""
    clean = re.sub(r"\s+", " ", title).replace('"', "'").strip()
    return clean if len(clean) <= TITLE_MAX else clean[: TITLE_MAX - 1] + "…"


def name_cards(prompt: str, cards: list[tuple[int, str]]) -> str:
    """Append the cards the session is about, so a later selection change cannot alter them."""
    if not cards:
        return prompt
    names = ", ".join(f'#{card_id} "{short_title(title)}"' for card_id, title in cards)
    return f"{prompt}\n\nCards: {names}"


def card_titles(engine: Engine, card_ids: list[int]) -> list[tuple[int, str]]:
    """(id, title) for each existing card, in the given order."""
    if not card_ids:
        return []
    with Session(engine) as session:
        rows = session.exec(
            select(Card.id, Item.title).join(Item, Item.id == Card.item_id).where(
                Card.id.in_(card_ids)  # type: ignore[union-attr]
            )
        ).all()
    titles = {card_id: title for card_id, title in rows}
    return [(card_id, titles[card_id]) for card_id in card_ids if card_id in titles]


class HandoffStore:
    """Prompts too long for a link, kept in memory for a day for `get_handoff`."""

    def __init__(
        self, ttl: timedelta = HANDOFF_TTL, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._ttl = ttl
        self._now = now
        self._items: dict[str, tuple[str, datetime]] = {}
        # The HTTP endpoint and the MCP tools run on different threads.
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            self._prune()
            return len(self._items)

    def _prune(self) -> None:
        cutoff = self._now() - self._ttl
        for key in [k for k, (_, at) in self._items.items() if at < cutoff]:
            del self._items[key]

    def put(self, text: str) -> str:
        """Store `text` and return the id the session asks for."""
        with self._lock:
            self._prune()
            handoff_id = secrets.token_urlsafe(6)
            self._items[handoff_id] = (text, self._now())
            return handoff_id

    def get(self, handoff_id: str) -> str | None:
        """The stored text, or None when unknown or expired."""
        with self._lock:
            self._prune()
            item = self._items.get(handoff_id)
            return item[0] if item else None


def session_link(prompt: str, folder: Path, handoffs: HandoffStore) -> str:
    """The link for `prompt`, swapping a long prompt for a hand-off pointer. Each call spells the
    folder differently from the call before (see folder_text)."""
    folder = folder_text(folder, next(_folder_turns))
    url = desktop_link(prompt, folder)
    if len(url) <= LINK_MAX:
        return url
    handoff_id = handoffs.put(prompt)
    pointer = (
        f"Use the spyglass skill: call the get_handoff tool with id {handoff_id} and follow "
        "what it returns."
    )
    about = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
    # Show how the request begins, as long as the link stays short (non-Latin text grows ninefold
    # when encoded).
    while about:
        url = desktop_link(f"{pointer} It begins: {about}", folder)
        if len(url) <= LINK_MAX:
            return url
        about = about[: len(about) // 2]
    return desktop_link(pointer, folder)
