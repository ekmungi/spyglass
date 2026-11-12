"""Tests for the weekly upkeep: what is removed, and above all what must never be."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Content, Item, RunLog
from spyglass_service.radar import housekeeping
from spyglass_service.radar.housekeeping import compact_database, prune_folder, run_housekeeping
from spyglass_service.radar.models import (
    AssistMessage,
    AssistThread,
    Assessment,
    ItemState,
    RadarBrief,
    ReaderDoc,
    Signal,
    dumps,
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def ago(days: float) -> datetime:
    """A naive UTC time `days` before NOW, as the database stores times."""
    return (NOW - timedelta(days=days)).replace(tzinfo=None)


@pytest.fixture
def engine(tmp_path):
    eng = create_db_engine(tmp_path / "t.db")
    init_db(eng)
    yield eng
    eng.dispose()


def settings(tmp_path, days: int = 120):
    return SimpleNamespace(radar_retention_days=days, data_dir=tmp_path)


def add_item(engine, n: int, age_days: float = 200, *, stored: bool = True) -> int:
    """An item fetched `age_days` ago with a reader document, stored text and an assessment."""
    with Session(engine) as session:
        item = Item(source="rss", external_id=f"x{n}", title=f"Title {n}", url=f"https://e.com/{n}",
                    fetched_at=ago(age_days))
        session.add(item)
        session.commit()
        session.refresh(item)
        item_id = item.id
        session.add(Assessment(item_id=item_id, tier="notable", score=60))
        if stored:
            session.add(ReaderDoc(item_id=item_id, html="<p>body</p>"))
        session.commit()
    if stored:
        content_store.store_fulltext(engine, item_id=item_id, markdown=f"zebrafinch text {n}")
    return item_id


def has_text(engine, item_id: int) -> bool:
    with Session(engine) as session:
        return session.exec(select(Content).where(Content.item_id == item_id)).first() is not None


def has_reader(engine, item_id: int) -> bool:
    with Session(engine) as session:
        return session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first() is not None


def fts_rows(engine, item_id: int) -> int:
    with Session(engine) as session:
        return session.connection().execute(
            text("SELECT count(*) FROM content_fts WHERE item_id = :i"), {"i": item_id}).scalar()


def item_exists(engine, item_id: int) -> bool:
    with Session(engine) as session:
        return session.get(Item, item_id) is not None and session.exec(
            select(Assessment).where(Assessment.item_id == item_id)).first() is not None


# ---- (a) stored text and reader documents --------------------------------------------------

def test_old_untouched_item_loses_text_and_reader_document_but_keeps_item_and_assessment(
        engine, tmp_path):
    item_id = add_item(engine, 1)
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert not has_text(engine, item_id) and not has_reader(engine, item_id)
    assert fts_rows(engine, item_id) == 0
    assert item_exists(engine, item_id)
    assert result["retention"] == {"items": 1, "reader_docs": 1, "contents": 1}


def test_a_recent_item_is_left_alone(engine, tmp_path):
    item_id = add_item(engine, 1, age_days=30)
    run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert has_text(engine, item_id) and has_reader(engine, item_id)


def test_the_cutoff_is_the_retention_setting(engine, tmp_path):
    item_id = add_item(engine, 1, age_days=45)
    run_housekeeping(engine, settings(tmp_path, days=30), now=NOW)
    assert not has_text(engine, item_id)


def test_zero_days_keeps_everything(engine, tmp_path):
    item_id = add_item(engine, 1, age_days=900)
    result = run_housekeeping(engine, settings(tmp_path, days=0), now=NOW)
    assert has_text(engine, item_id) and has_reader(engine, item_id)
    assert result["retention"] == {"skipped": "retention is switched off"}


INTERACTIONS = {
    "opened_at": lambda s, i: s.add(ItemState(item_id=i, opened_at=ago(100))),
    "open_count": lambda s, i: s.add(ItemState(item_id=i, open_count=2)),
    "read_seconds": lambda s, i: s.add(ItemState(item_id=i, read_seconds=40)),
    "saved": lambda s, i: s.add(ItemState(item_id=i, saved_at=ago(100))),
    "vote": lambda s, i: s.add(ItemState(item_id=i, vote="more")),
    "from_user": lambda s, i: s.add(ItemState(item_id=i, from_user=True)),
    "vault_path": lambda s, i: s.add(ItemState(item_id=i, vault_path="Saved/a.md")),
    "hidden": lambda s, i: s.add(ItemState(item_id=i, hidden=True)),
    "user_note": lambda s, i: s.add(ItemState(item_id=i, user_note="mine")),
    "signal": lambda s, i: s.add(Signal(item_id=i, kind="open", at=ago(100))),
    "asked": lambda s, i: s.add(AssistThread(item_id=i, created_at=ago(100))),
}


@pytest.mark.parametrize("how", sorted(INTERACTIONS))
def test_an_item_the_reader_touched_is_never_cleaned(engine, tmp_path, how):
    item_id = add_item(engine, 1)
    with Session(engine) as session:
        INTERACTIONS[how](session, item_id)
        session.commit()
    run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert has_text(engine, item_id) and has_reader(engine, item_id)


def test_an_item_shown_in_a_brief_is_never_cleaned(engine, tmp_path):
    lead, source, other = add_item(engine, 1), add_item(engine, 2), add_item(engine, 3)
    doc = {"day": "2026-08-01", "sections": [{"key": "top", "stories": [
        {"id": f"s-{lead}", "item_id": lead, "sources": [{"item_id": lead}, {"item_id": source}]}]}]}
    with Session(engine) as session:
        session.add(RadarBrief(day="2026-08-01", doc=dumps(doc), created_at=ago(100)))
        session.commit()
    run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert has_text(engine, lead) and has_text(engine, source)
    assert not has_text(engine, other)


def test_a_corrupt_brief_document_does_not_stop_the_cleaning(engine, tmp_path):
    item_id = add_item(engine, 1)
    with Session(engine) as session:
        session.add(RadarBrief(day="2026-08-01", doc="{not json", created_at=ago(100)))
        session.commit()
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert not has_text(engine, item_id) and "error" not in result["retention"]


def test_an_item_with_only_a_reader_document_or_only_text_is_handled(engine, tmp_path):
    only_reader = add_item(engine, 1, stored=False)
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=only_reader, html="<p>x</p>"))
        session.commit()
    only_text = add_item(engine, 2, stored=False)
    content_store.store_fulltext(engine, item_id=only_text, markdown="solo")
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert not has_reader(engine, only_reader) and not has_text(engine, only_text)
    assert result["retention"]["reader_docs"] == 1 and result["retention"]["contents"] == 1


# ---- (b) (c) history -----------------------------------------------------------------------

def test_old_signals_and_run_logs_are_deleted_and_recent_ones_kept(engine, tmp_path):
    with Session(engine) as session:
        session.add(Signal(item_id=None, kind="old", at=ago(401)))
        session.add(Signal(item_id=None, kind="new", at=ago(399)))
        session.add(RunLog(source="rss", status="ok", started_at=ago(91)))
        session.add(RunLog(source="rss", status="ok", started_at=ago(89)))
        session.commit()
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    with Session(engine) as session:
        assert [s.kind for s in session.exec(select(Signal)).all()] == ["new"]
        assert len(session.exec(select(RunLog)).all()) == 1
    assert result["history"] == {"signals": 1, "run_logs": 1}


def test_old_briefs_are_deleted_and_recent_ones_kept(engine, tmp_path):
    with Session(engine) as session:
        session.add(RadarBrief(day="2025-01-01", doc="{}", created_at=ago(401)))
        session.add(RadarBrief(day="2026-11-11", doc="{}", created_at=ago(1)))
        session.commit()
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    with Session(engine) as session:
        assert [b.day for b in session.exec(select(RadarBrief)).all()] == ["2026-11-11"]
    assert result["briefs"] == {"deleted": 1}


# ---- (d) caches ----------------------------------------------------------------------------

def make_files(folder, sizes_oldest_first: list[int]):
    folder.mkdir()
    paths = []
    for index, size in enumerate(sizes_oldest_first):
        path = folder / f"{index}.bin"
        path.write_bytes(b"x" * size)
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        paths.append(path)
    return paths


def test_prune_folder_removes_the_oldest_files_until_it_fits(tmp_path):
    paths = make_files(tmp_path / "c", [400, 400, 400])
    assert prune_folder(tmp_path / "c", 800) == 1
    assert not paths[0].exists() and paths[1].exists() and paths[2].exists()


def test_prune_folder_leaves_a_cache_that_fits_and_a_missing_folder(tmp_path):
    make_files(tmp_path / "c", [100, 100])
    assert prune_folder(tmp_path / "c", 1000) == 0
    assert prune_folder(tmp_path / "missing", 10) == 0


def test_housekeeping_prunes_both_caches_to_their_bounds(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(housekeeping, "PDF_CACHE_BYTES", 150)
    monkeypatch.setattr(housekeeping, "IMG_CACHE_BYTES", 150)
    make_files(tmp_path / "pdf_cache", [100, 100])
    make_files(tmp_path / "img_cache", [100, 100, 100])
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert result["caches"] == {"pdf_cache": 1, "img_cache": 2}


def test_housekeeping_without_cache_folders_is_fine(engine, tmp_path):
    assert run_housekeeping(engine, settings(tmp_path), now=NOW)["caches"] == {
        "pdf_cache": 0, "img_cache": 0}


def test_housekeeping_keeps_what_you_sent_in_and_reports_the_store_size(engine, tmp_path, monkeypatch):
    """Files sent in are moved out of the caches before the caches are trimmed; the store is reported."""
    from spyglass_service.radar import from_you_store, media_proxy
    from spyglass_service.radar.import_image import image_fields

    url = "https://team.slack.com/files/U1/F200/chart.png"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    with Session(engine) as session:
        item = Item(source="capture", external_id=url, title="chart", url=url)
        session.add(item)
        session.commit()
        session.add(ReaderDoc(item_id=item.id, html=image_fields(url, "chart", None)["html"],
                              lead_image=url, source_url=url))
        session.add(ItemState(item_id=item.id, from_user=True, captured_via="slack"))
        session.commit()
        item_id = item.id
    media_proxy.cache_put(tmp_path / "img_cache", url, png, "image/png")
    monkeypatch.setattr(housekeeping, "IMG_CACHE_BYTES", 0)

    result = run_housekeeping(engine, settings(tmp_path), now=NOW)

    assert result["from_you"] == {"images": 1, "pdfs": 0, "stored_bytes": len(png)}
    assert from_you_store.find(tmp_path, item_id)[0].read_bytes() == png
    assert media_proxy.serve(engine, tmp_path, url) == (png, "image/png")
    assert run_housekeeping(engine, settings(tmp_path), now=NOW)["from_you"]["images"] == 0


# ---- (e) empty threads ---------------------------------------------------------------------

def test_empty_threads_older_than_a_week_go_and_threads_with_messages_stay(engine, tmp_path):
    with Session(engine) as session:
        old_empty = AssistThread(created_at=ago(8), updated_at=ago(8))
        old_used = AssistThread(created_at=ago(8), updated_at=ago(8))
        new_empty = AssistThread(created_at=ago(2), updated_at=ago(2))
        session.add_all([old_empty, old_used, new_empty])
        session.commit()
        session.add(AssistMessage(thread_id=old_used.id, role="user", content="hi"))
        session.commit()
        keep = {old_used.id, new_empty.id}
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    with Session(engine) as session:
        assert {t.id for t in session.exec(select(AssistThread)).all()} == keep
    assert result["threads"] == {"deleted": 1}


# ---- (f) database space --------------------------------------------------------------------

def test_compaction_reports_reclaimable_space_on_an_ordinary_database(engine):
    report = compact_database(engine)
    assert report["auto_vacuum"] == "none" and report["reclaimed_bytes"] == 0
    assert report["reclaimable_bytes"] >= 0


def test_compaction_gives_back_free_pages_when_the_database_allows_it(tmp_path):
    path = tmp_path / "inc.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    con.execute("CREATE TABLE t (b BLOB)")
    con.executemany("INSERT INTO t VALUES (?)", [(b"x" * 4000,) for _ in range(200)])
    con.commit()
    con.execute("DELETE FROM t")
    con.commit()
    con.close()
    eng = create_db_engine(path)
    try:
        before = os.path.getsize(path)
        report = compact_database(eng)
        assert report["auto_vacuum"] == "incremental"
        assert report["reclaimed_bytes"] > 0
        assert os.path.getsize(path) < before
    finally:
        eng.dispose()


# ---- isolation -----------------------------------------------------------------------------

def test_a_failing_step_is_reported_and_the_others_still_run(engine, tmp_path, monkeypatch):
    item_id = add_item(engine, 1)

    def boom(*args, **kwargs):
        raise RuntimeError("history broke")

    monkeypatch.setattr(housekeeping, "_prune_history", boom)
    result = run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert "history broke" in result["history"]["error"]
    assert not has_text(engine, item_id)
    assert result["ok"] is False and "error" not in result["briefs"]


def test_a_second_run_changes_nothing(engine, tmp_path):
    add_item(engine, 1)
    run_housekeeping(engine, settings(tmp_path), now=NOW)
    again = run_housekeeping(engine, settings(tmp_path), now=NOW)
    assert again["retention"] == {"items": 0, "reader_docs": 0, "contents": 0}
    assert again["ok"] is True
