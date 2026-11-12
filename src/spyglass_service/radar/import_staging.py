"""A short-lived waiting room for pages handed over from the reader's browser.

The "Send to Spyglass" bookmark button can post a page from any site, so nothing it sends is
imported on receipt. The page is parked here under a random token until the reader confirms it in
Spyglass itself, discards it, or it expires. The area is bounded so repeated posts cannot fill the
disk: at most `MAX_ENTRIES` pages, at most `MAX_TOTAL_BYTES` in total, each kept for `TTL_SECONDS`;
when a new page would break a limit the oldest pages are dropped first.

A staged page can hold whatever the reader's signed-in session showed, so its content is never
logged, and its file is deleted when it is taken, discarded or expires. A background sweep (one
daemon thread, started by the first page staged) deletes expired pages every `SWEEP_SECONDS`, so a
page the reader never answered does not wait on disk for the next import.
"""

import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 16 random bytes = 128 bits, written as 32 hex characters; also the file name.
TOKEN_BYTES = 16
_TOKEN = re.compile(r"[0-9a-f]{32}")
# How long a page waits for the reader's answer.
TTL_SECONDS = 15 * 60
# Upper bounds on what may wait at once, whoever is posting.
MAX_ENTRIES = 20
MAX_TOTAL_BYTES = 60 * 1024 * 1024
# Largest page accepted, counted in UTF-8 bytes (the bookmark button sends at most 6 MB).
MAX_HTML_BYTES = 6 * 1024 * 1024
MAX_TITLE_CHARS = 500
# An origin is at most a scheme, a host name and a port.
MAX_SENDER_CHARS = 200
_SUFFIX = ".json"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")

# One lock for every staging folder: staging is rare and quick, and one lock keeps the
# check-the-limits-then-write step atomic across request threads.
_LOCK = threading.Lock()
# How often the background sweep deletes expired pages.
SWEEP_SECONDS = 60
# Every staging area used since start-up (by folder), and the one thread that sweeps them.
_areas: dict[Path, "StagingArea"] = {}
_sweeper: threading.Thread | None = None


class StagingError(ValueError):
    """A page cannot be staged; the message says why in a sentence fit for the reader."""


class PageTooLarge(StagingError):
    """The page is over `MAX_HTML_BYTES`."""


@dataclass(frozen=True)
class StagedPage:
    """A page waiting for the reader's answer."""

    url: str
    title: str
    html: str
    sender: str | None
    created: float


def _clean_line(value: str | None, limit: int) -> str:
    """One line of plain text: control characters become spaces, then cut to `limit`."""
    return _CONTROL.sub(" ", value or "").strip()[:limit]


def valid_token(token: str) -> bool:
    """Whether `token` has the exact shape this module hands out (so it is safe as a file name)."""
    return isinstance(token, str) and _TOKEN.fullmatch(token) is not None


class StagingArea:
    """The staging folder, with its limits. Cheap to create; holds no state but the folder."""

    def __init__(self, folder: Path, *, clock: Callable[[], float] = time.time) -> None:
        """Use `folder` (created on first write); `clock` returns the time in seconds."""
        self.folder = folder
        self._clock = clock

    def _path(self, token: str) -> Path:
        """The file of a token; raises LookupError for anything that is not a token."""
        if not valid_token(token):
            raise LookupError("unknown token")
        return self.folder / f"{token}{_SUFFIX}"

    def _entries(self) -> list[tuple[float, int, Path]]:
        """(modified time, size, path) of every file in the folder, oldest first."""
        if not self.folder.is_dir():
            return []
        found = []
        for path in self.folder.iterdir():
            try:
                info = path.stat()
            except OSError:
                continue
            found.append((info.st_mtime, info.st_size, path))
        return sorted(found)

    def _expired(self, modified: float) -> bool:
        """Whether a file written at `modified` is past its time."""
        return self._clock() - modified > TTL_SECONDS

    def purge(self) -> int:
        """Delete every expired file (pages and half-written leftovers); returns how many."""
        removed = 0
        for modified, _, path in self._entries():
            if not self._expired(modified):
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:  # open elsewhere for a moment (Windows): the next sweep retries
                logger.warning("could not delete an expired staged page (%s)", exc.__class__.__name__)
                continue
            removed += 1
        return removed

    def _make_room(self, incoming: int) -> None:
        """Drop the oldest pages until one more page of `incoming` bytes fits the limits."""
        entries = [e for e in self._entries() if e[2].suffix == _SUFFIX]
        total = sum(size for _, size, _ in entries)
        while entries and (len(entries) >= MAX_ENTRIES or total + incoming > MAX_TOTAL_BYTES):
            _, size, path = entries.pop(0)
            path.unlink(missing_ok=True)
            total -= size

    def stage(self, url: str, title: str, html: str, sender: str | None = None) -> str:
        """Park a page and return its token.

        `url` must already be validated by the caller. Raises StagingError for an empty page or
        one over `MAX_HTML_BYTES`.
        """
        if not (html or "").strip():
            raise StagingError("The page arrived empty.")
        if len(html.encode("utf-8", "surrogatepass")) > MAX_HTML_BYTES:
            raise PageTooLarge("The page is larger than 6 MB.")
        record = {"url": url, "title": _clean_line(title, MAX_TITLE_CHARS),
                  "sender": _clean_line(sender, MAX_SENDER_CHARS) or None, "html": html}
        data = json.dumps(record).encode("utf-8")
        token = secrets.token_hex(TOKEN_BYTES)
        with _LOCK:
            self.folder.mkdir(parents=True, exist_ok=True)
            _watch(self)
            self.purge()
            self._make_room(len(data))
            final = self._path(token)
            temporary = self.folder / f"{token}.tmp"
            temporary.write_bytes(data)
            now = self._clock()
            os.utime(temporary, (now, now))
            os.replace(temporary, final)
        return token

    def _read(self, path: Path) -> StagedPage:
        """Read a page file; a missing, expired or damaged file is LookupError."""
        try:
            modified = path.stat().st_mtime
            if self._expired(modified):
                path.unlink(missing_ok=True)
                raise LookupError("expired")
            record = json.loads(path.read_text(encoding="utf-8"))
            return StagedPage(url=str(record["url"]), title=str(record.get("title") or ""),
                              html=str(record["html"]), sender=record.get("sender") or None,
                              created=modified)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LookupError("unknown token") from exc

    def peek(self, token: str) -> StagedPage:
        """The page behind a token, left in place (for the preview). LookupError when unknown."""
        return self._read(self._path(token))

    def take(self, token: str) -> StagedPage:
        """The page behind a token, removed so the token cannot be used again.

        The file is first renamed to a name only this call knows, so two simultaneous calls with
        the same token cannot both get the page.
        """
        path = self._path(token)
        claimed = self.folder / f"{token}.{secrets.token_hex(4)}.taking"
        try:
            os.replace(path, claimed)
        except OSError as exc:  # already taken, discarded, expired or never staged
            raise LookupError("unknown token") from exc
        try:
            return self._read(claimed)
        finally:
            claimed.unlink(missing_ok=True)

    def discard(self, token: str) -> bool:
        """Delete the page behind a token; False when there was none."""
        try:
            path = self._path(token)
        except LookupError:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True


def _watch(area: StagingArea) -> None:
    """Remember an area for the background sweep and start the sweep once (caller holds _LOCK)."""
    global _sweeper
    _areas[area.folder] = area
    if _sweeper is None or not _sweeper.is_alive():
        _sweeper = threading.Thread(target=_sweep_forever, name="import-staging-sweep", daemon=True)
        _sweeper.start()


def sweep_once() -> int:
    """Delete the expired pages of every staging area used so far; returns how many files went."""
    with _LOCK:
        areas = list(_areas.values())
    removed = 0
    for area in areas:
        try:
            removed += area.purge()
        except OSError as exc:  # a locked or vanished file: tried again on the next sweep
            logger.warning("could not sweep the import staging folder (%s)", exc.__class__.__name__)
    return removed


def _sweep_forever() -> None:
    """The sweeper thread's loop."""
    while True:
        time.sleep(SWEEP_SECONDS)
        sweep_once()
