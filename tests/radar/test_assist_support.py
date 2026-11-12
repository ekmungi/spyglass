"""Shared helpers for the assistant tests: settings, a throwaway database, a fake keyring, a
scripted engine and SSE responses. (No tests live here.)"""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import keyring
import pytest
from keyring.backend import KeyringBackend
from sqlmodel import Session

from spyglass_service import content_store
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.engines.openai_compat import clear_probe_cache
from spyglass_service.radar.models import Assessment, ItemState, dumps

SECRET_NAMES = ("OPENROUTER_API_KEY", "SPYGLASS_OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
                "SPYGLASS_ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SPYGLASS_OPENAI_API_KEY")


class MemoryKeyring(KeyringBackend):
    """An in-memory keyring so tests never touch the real operating-system store."""

    priority = 1

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        """Return the stored value or None."""
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        """Store a value."""
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        """Remove a value; a missing one raises like a real backend."""
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.store[(service, username)]


@pytest.fixture
def memory_keyring() -> Iterator[MemoryKeyring]:
    """Install the in-memory keyring for the test and restore the previous one afterwards."""
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def clean_assist_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real API key from the environment, and no remembered local-server probes."""
    for name in SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    clear_probe_cache()


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Settings that ignore .env and keep their data in tmp_path."""
    return Settings(_env_file=None, data_dir=tmp_path / "data", **overrides)


@pytest.fixture
def db(tmp_path: Path) -> Iterator:
    """A fresh database engine with every table, disposed afterwards."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    yield engine
    engine.dispose()


def add_item(db, title: str = "Robot completes surgery", text: str | None = "Body text. " * 20,
             *, url: str = "https://example.org/a", note: str | None = None) -> int:
    """Insert an item (with assessment, optional full text and reader note); return its id."""
    with Session(db) as session:
        item = Item(source="rss", external_id=url, title=title, url=url, origin="Example News")
        session.add(item)
        session.commit()
        session.refresh(item)
        session.add(Assessment(item_id=item.id, stage="digest", score=80, tier="top",
                               section="health", kind="news", headline="A robot did surgery",
                               why="Relevant to endoscopy work.",
                               key_points=dumps(["First point", "Second point"]),
                               entities=dumps(["Acme Robotics"])))
        if note:
            session.add(ItemState(item_id=item.id, user_note=note))
        session.commit()
        item_id = item.id
    if text is not None:
        content_store.store_fulltext(db, item_id=item_id, markdown=text, source_url=url)
    return item_id


class FakeEngine:
    """An engine that plays back scripted events and records how it was called."""

    kind = "api"

    def __init__(self, events: list[StreamEvent], *, id: str = "fake") -> None:  # noqa: A002
        """`events` are yielded in order."""
        self.id, self.label = id, "Fake"
        self.events = events
        self.calls: list[dict] = []
        self.closed = False

    def models(self) -> list[dict]:
        """One model."""
        return [{"id": "m1", "label": "m1"}]

    def available(self) -> tuple[bool, str | None]:
        """Always usable."""
        return True, None

    def stream(self, *, system: str, messages: list[dict], model: str,
               session: str | None = None) -> Iterator[StreamEvent]:
        """Record the call, then play the script; mark closed in finally."""
        self.calls.append({"system": system, "messages": messages, "model": model,
                           "session": session})
        try:
            yield from self.events
        finally:
            self.closed = True


def patch_fake_engine(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> None:
    """Make the registry offer only `engine` (as the default) for thread tests."""
    row = {"id": engine.id, "label": "Fake", "kind": "api", "available": True, "reason": None,
           "models": engine.models(), "default_model": "m1", "is_default": True}
    monkeypatch.setattr("spyglass_service.radar.assist.registry.list_engines",
                        lambda settings, session=None, transport=None: [row])
    monkeypatch.setattr("spyglass_service.radar.assist.registry.get_engine",
                        lambda settings, engine_id, session=None, transport=None: engine)


def sse_body(*payloads: dict | str, comments: bool = False) -> bytes:
    """An OpenAI-style SSE body: one data frame per payload, then [DONE]."""
    frames = [": keep-alive\n\n"] if comments else []
    for payload in payloads:
        frames.append(f"data: {payload if isinstance(payload, str) else json.dumps(payload)}\n\n")
    frames.append("data: [DONE]\n\n")
    return "".join(frames).encode()


def delta(text: str) -> dict:
    """An OpenAI-style streaming chunk carrying `text`."""
    return {"choices": [{"delta": {"content": text}}]}


def split_response(body: bytes, size: int = 7, status: int = 200) -> httpx.Response:
    """A response whose body arrives in small chunks that end mid-line."""
    chunks = [body[i:i + size] for i in range(0, len(body), size)]
    return httpx.Response(status, content=iter(chunks),
                          headers={"content-type": "text/event-stream"})
