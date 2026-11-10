"""Tests for the paper inbox core."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.inbox import (
    add_paper,
    file_paper,
    finish_run,
    inbox_view,
    last_watermark,
    start_run,
)
from spyglass_service.models import Card, CardState, InboxEntry, InboxRun, Item


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def test_a_run_files_a_paper_and_moves_the_watermark(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    run = start_run(engine)
    assert run["since"] is None
    added = add_paper(
        engine, run["run_id"], "https://arxiv.org/abs/2410.00001",
        message_text="look at this for Spyglass", message_ts="1728900000.000100",
    )
    assert added["already_known"] is False
    file_paper(
        engine, added["entry_id"], title="A paper on agents", summary="It shows X.",
        note_path="/vault/03 RESOURCES/Papers/A paper on agents.md", full_text=True,
    )
    finish_run(engine, run["run_id"], ok=True, watermark="1728900000.000100")
    assert last_watermark(engine) == "1728900000.000100"
    view = inbox_view(engine, "paper-inbox")
    assert view["channel"] == "paper-inbox"
    assert view["last_run"]["status"] == "ok" and view["last_run"]["papers"] == 1
    [paper] = view["papers"]
    assert paper["title"] == "A paper on agents"
    assert paper["summary"] == "It shows X."
    assert paper["note_path"].endswith("A paper on agents.md")
    assert paper["message_text"] == "look at this for Spyglass"
    assert paper["full_text"] is True and paper["filed"] is True
    with Session(engine) as session:
        card = session.exec(select(Card)).one()
        item = session.exec(select(Item)).one()
    assert card.state == CardState.FINISHED and card.curated is True
    assert item.source == "inbox" and item.origin == "Slack"


def test_a_failed_run_keeps_the_watermark(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    first = start_run(engine)
    finish_run(engine, first["run_id"], ok=True, watermark="100.1")
    second = start_run(engine)
    assert second["since"] == "100.1"
    finish_run(engine, second["run_id"], ok=False, watermark="200.2", error="Slack not connected")
    assert last_watermark(engine) == "100.1"
    run = inbox_view(engine, "")["last_run"]
    assert run["status"] == "error" and run["error"] == "Slack not connected"


def test_a_paper_shared_twice_is_one_card_with_two_entries(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    run = start_run(engine)
    first = add_paper(engine, run["run_id"], "https://example.org/paper?utm_source=slack")
    again = add_paper(engine, run["run_id"], "https://example.org/paper")
    assert again["card_id"] == first["card_id"]
    assert again["already_known"] is True
    view = inbox_view(engine, "")
    assert len(view["papers"]) == 2
    assert {p["shared"] for p in view["papers"]} == {2}


def test_a_paper_already_collected_from_a_feed_reuses_its_card(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        item = Item(source="rss", external_id="x", title="Feed title", url="https://example.org/a")
        session.add(item)
        session.commit()
        card = Card(item_id=item.id, summary="")
        session.add(card)
        session.commit()
        card_id = card.id
    run = start_run(engine)
    added = add_paper(engine, run["run_id"], "https://example.org/a", title="Other title")
    assert added["card_id"] == card_id
    entry = added["entry_id"]
    file_paper(engine, entry, title="Other title", summary="s", note_path="/n.md")
    assert inbox_view(engine, "")["papers"][0]["title"] == "Feed title"


def test_a_run_that_never_finished_shows_as_failed(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    run = start_run(engine)
    with Session(engine) as session:
        row = session.get(InboxRun, run["run_id"])
        row.started_at = datetime.now(UTC) - timedelta(hours=3)
        session.add(row)
        session.commit()
    last = inbox_view(engine, "")["last_run"]
    assert last["status"] == "error"
    assert "did not finish" in last["error"]


def test_unknown_ids_are_reported_not_raised(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    assert file_paper(engine, 999, summary="s") is None
    assert finish_run(engine, 999, ok=True) is None
    assert inbox_view(engine, "")["last_run"] is None
    with Session(engine) as session:
        assert session.exec(select(InboxEntry)).all() == []


def test_a_retried_run_reuses_the_entry_for_the_same_message(tmp_path: Path) -> None:
    """Review: a failed run is retried from the same watermark; its papers must not double."""
    engine = make_engine(tmp_path)
    failed = start_run(engine)
    first = add_paper(engine, failed["run_id"], "https://example.org/p", message_ts="10.1")
    finish_run(engine, failed["run_id"], ok=False, error="closed")
    retry = start_run(engine)
    again = add_paper(engine, retry["run_id"], "https://example.org/p", message_ts="10.1")
    assert again["entry_id"] == first["entry_id"]
    assert again["already_known"] is False
    view = inbox_view(engine, "")
    assert len(view["papers"]) == 1 and view["papers"][0]["shared"] == 1
    assert view["last_run"]["papers"] == 1


def test_the_watermark_is_the_newest_message_not_the_latest_run(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    a, b = start_run(engine), start_run(engine)
    finish_run(engine, b["run_id"], ok=True, watermark="200.0")
    finish_run(engine, a["run_id"], ok=True, watermark="100.0")
    assert last_watermark(engine) == "200.0"


def test_a_feed_item_stored_under_another_form_of_the_link_is_reused(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    ids = {}
    with Session(engine) as session:
        for key, url in [("blog", "https://blog.example/post?utm_source=rss"),
                         ("arxiv", "https://arxiv.org/abs/2410.00009")]:
            item = Item(source="rss", external_id=key, title=key, url=url)
            session.add(item)
            session.commit()
            card = Card(item_id=item.id, summary="")
            session.add(card)
            session.commit()
            ids[key] = card.id
    run = start_run(engine)
    assert add_paper(engine, run["run_id"], "https://blog.example/post")["card_id"] == ids["blog"]
    assert add_paper(engine, run["run_id"], "https://arxiv.org/pdf/2410.00009")["card_id"] == ids["arxiv"]


def test_only_web_links_and_known_runs_are_accepted(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    assert add_paper(engine, None, "javascript:alert(1)")["error"] == "bad_url"
    assert add_paper(engine, 999, "https://example.org/p")["error"] == "not_found"


def test_a_vault_relative_note_is_stored_absolute(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    run = start_run(engine)
    added = add_paper(engine, run["run_id"], "https://example.org/p")
    file_paper(engine, added["entry_id"], note_path="Papers/P.md", vault=tmp_path / "vault")
    assert inbox_view(engine, "")["papers"][0]["note_path"] == str(tmp_path / "vault" / "Papers/P.md")
