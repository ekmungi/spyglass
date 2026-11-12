"""Shared pytest fixtures.

Globally replaces the FastEmbed-backed embedder with a deterministic CPU fake so that NO test
ever downloads the arctic-embed-s model. Any test that constructs the app and enters its
lifespan will call `ensure_index()`, which builds the real embedder unless this fake is installed.
"""

import hashlib
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from spyglass_service.embeddings import ARCTIC_DIM


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic ARCTIC_DIM-wide float32 vectors derived from each text (no model needed)."""
    out = []
    for t in texts:
        seed = int.from_bytes(hashlib.blake2b(t.encode(), digest_size=8).digest(), "big")
        out.append(np.random.default_rng(seed).standard_normal(ARCTIC_DIM))
    return np.array(out, dtype=np.float32)


@pytest.fixture(autouse=True)
def _no_real_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every ensure_index()/fastembed_embedder() call to use the deterministic fake."""
    monkeypatch.setattr(
        "spyglass_service.embeddings.fastembed_embedder", lambda *args, **kwargs: _fake_embed
    )


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer every host-name lookup of the address guard with a fixed public address.

    The older fetch paths now pass the guard, which looks a name up before each request; this
    keeps every test off DNS. A test that needs a private answer patches `netguard.resolve`.
    """
    monkeypatch.setattr("spyglass_service.radar.netguard.resolve", lambda host: ["93.184.216.34"])


@pytest.fixture(autouse=True)
def _nullpool_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every test-created engine onto NullPool so DB connections close on return.

    Tests create many short-lived engines via create_db_engine and rarely dispose them;
    a pooled connection then lives until garbage collection, which raises a late
    ResourceWarning that the suite's `filterwarnings = error` turns into a failure
    attributed to whatever test was running when GC fired (a flaky, ordering-dependent
    cascade). NullPool closes each DBAPI connection the moment its Connection is released,
    so nothing survives to be collected late. Patches the create_engine reference inside
    spyglass_service.db, so it applies no matter how a test imported create_db_engine.
    Production is unaffected (it keeps the default pool).
    """
    import spyglass_service.db as db_module
    from sqlalchemy.pool import NullPool

    real_create_engine = db_module.create_engine

    def _nullpool_create_engine(*args, **kwargs):
        kwargs.setdefault("poolclass", NullPool)
        return real_create_engine(*args, **kwargs)

    monkeypatch.setattr(db_module, "create_engine", _nullpool_create_engine)


@pytest.fixture(autouse=True)
def _no_real_data_dir_migration(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Point the legacy data dir at a non-existent path so app startup never migrates the
    real %LOCALAPPDATA%/Spyglass into a test's tmp dir. Tests of migrate_data_dir
    itself pass an explicit legacy_dir and are unaffected."""
    monkeypatch.setattr(
        "spyglass_service.migrate_data_dir.legacy_data_dir", lambda: tmp_path / "no-legacy"
    )


@pytest.fixture(autouse=True)
def _fetch_worker_off_unless_requested(request: pytest.FixtureRequest, monkeypatch) -> None:
    """Neuter FetchWorker.start() by default so no test silently performs a real fetch.

    On-demand full-text fetch runs on a background worker that the app starts
    in its lifespan. Any test that POSTs /fulltext would otherwise have that worker pick
    the job up and run the REAL acquisition ladder over the network -- slow, flaky, and
    invisible until a stray SSL socket shows up in an unrelated failure.

    Tests that genuinely exercise the worker opt in with @pytest.mark.live_fetch_worker.
    """
    if "live_fetch_worker" in request.keywords:
        return
    from spyglass_service.fetch_worker import FetchWorker

    monkeypatch.setattr(FetchWorker, "start", lambda self: None)


@pytest.fixture(autouse=True)
def _claude_worker_off(monkeypatch) -> None:
    """Never start the background-job worker in tests: it would run a real `claude`.

    Job tests drive ClaudeJobWorker.run_one directly with a fake Claude run.
    """
    from spyglass_service.job_worker import ClaudeJobWorker

    monkeypatch.setattr(ClaudeJobWorker, "start", lambda self: None)


@pytest.fixture(autouse=True)
def _test_client_host_allowed(monkeypatch) -> None:
    """Let the service answer the test client, which addresses every request to "testserver".

    The service answers only Host 127.0.0.1 and localhost; this adds the test client's name
    through the environment, so production code never knows about it.
    """
    monkeypatch.setenv("SPYGLASS_ALLOWED_HOSTS", '["127.0.0.1", "localhost", "testserver"]')


class FakeObsidian:
    """Stands in for the Obsidian MCP server's vault_move.

    Renames the file inside the vault, as Obsidian would, and records every call as
    (source, destination). Set `error` to make the move fail with that message,
    `error_after_move` to move the note and then fail, `moves = False` to answer "ok" without
    moving anything, or `copies = True` to copy the note and leave the original.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error: str | None = None
        self.error_after_move: str | None = None
        self.moves = True
        self.copies = False

    async def __call__(self, settings, source: str, destination: str) -> None:
        # Imported here so a missing module fails the tests that need it, not every test.
        from spyglass_service.obsidian_move import ObsidianMoveError

        self.calls.append((source, destination))
        if self.error is not None:
            raise ObsidianMoveError(self.error)
        if not self.moves:
            return
        vault = settings.vault_path
        folder = vault / destination.rstrip("/")
        folder.mkdir(parents=True, exist_ok=True)
        if self.copies:
            shutil.copyfile(vault / source, folder / Path(source).name)
            return
        os.replace(vault / source, folder / Path(source).name)
        if self.error_after_move is not None:
            raise ObsidianMoveError(self.error_after_move)


@pytest.fixture()
def fake_obsidian() -> FakeObsidian:
    """A stand-in Obsidian server for tests of the service's own filing move."""
    return FakeObsidian()


@pytest.fixture()
def engine_with_card(tmp_path):
    """Engine with one Item (id=1, url set) and one Card (id=1, NEW state)."""

    from sqlmodel import Session

    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.models import Card, CardState, Item

    engine = create_db_engine(tmp_path / "spy_enrich.db")
    init_db(engine)
    with Session(engine) as session:
        item = Item(source="test", external_id="c1", title="Test Article",
                    url="https://example.test/article", summary="A blurb.")
        session.add(item)
        session.flush()
        card = Card(item_id=item.id, state=CardState.NEW, summary="")
        session.add(card)
        session.commit()
    return engine


@pytest.fixture()
def engine_with_two_cards(tmp_path):
    """Engine with two Items and two Cards; card1 already judged (relevance_at set), card2 fresh."""
    from datetime import UTC, datetime

    from sqlmodel import Session

    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.models import Card, CardState, Item

    engine = create_db_engine(tmp_path / "spy_enrich2.db")
    init_db(engine)
    with Session(engine) as session:
        item1 = Item(source="test", external_id="d1", title="Article One",
                     url="https://example.test/one", summary="Blurb one.")
        item2 = Item(source="test", external_id="d2", title="Article Two",
                     url="https://example.test/two", summary="Blurb two.")
        session.add(item1)
        session.add(item2)
        session.flush()
        card1 = Card(item_id=item1.id, state=CardState.NEW, summary="",
                     relevance_at=datetime.now(UTC))  # already judged
        card2 = Card(item_id=item2.id, state=CardState.NEW, summary="")  # fresh
        session.add(card1)
        session.add(card2)
        session.commit()
    return engine


@pytest.fixture()
def engine(tmp_path):
    """Bare engine with schema but no rows; used by enrich_is_stale and similar unit tests."""
    from spyglass_service.db import create_db_engine, init_db

    e = create_db_engine(tmp_path / "test.db")
    init_db(e)
    return e


@pytest.fixture()
def engine_with_item(tmp_path):
    """Provide a db engine (NullPool, via autouse patch) with one Item row (id=1) inserted.

    Used by the embed_summary and build_embedder seam tests, which need a
    pre-existing item to upsert an Embedding against.
    """
    from sqlmodel import Session

    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.models import Item

    engine = create_db_engine(tmp_path / "spy_summary.db")
    init_db(engine)
    with Session(engine) as session:
        item = Item(source="test", external_id="e1", title="Test Item",
                    url="https://example.test", summary="A test summary.")
        session.add(item)
        session.commit()
    return engine


@pytest.fixture()
def fixtures_web_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Serve `tests/fixtures` from a web server on this computer and return its base address.

    Feeds are read from the web only, so tests that need a real, parseable feed fetch it from here.
    The address guard refuses addresses on this computer in use; for the test its address decision
    is replaced (the guard's own behaviour is tested in tests/radar/test_legacy_guard.py).
    """
    import functools
    import http.server
    import threading

    from spyglass_service.radar import netguard

    handler = functools.partial(_QuietHandler, directory=str(Path(__file__).parent / "fixtures"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(netguard, "check_url", lambda url, resolver=None: netguard.Reach.PUBLIC)
    monkeypatch.setattr(netguard, "checked_addresses", lambda host: [host])
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _make_quiet_handler():
    """A static-file handler that logs nothing (the pytest output stays clean)."""
    import http.server

    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    return _Quiet


_QuietHandler = _make_quiet_handler()
