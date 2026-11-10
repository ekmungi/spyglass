"""Tests for the on-demand full-text fetch + store orchestration."""

from pathlib import Path

from sqlmodel import Session

from spyglass_service.content_store import get_fulltext
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.fulltext import fetch_card_fulltext
from spyglass_service.models import Card, Item


def make_engine(tmp_path: Path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def seed_card(engine, url: str = "https://x.test/a", title: str = "T") -> tuple[int, int]:
    """Insert an item + card; return (card_id, item_id)."""
    with Session(engine) as session:
        item = Item(source="rss", external_id="a", title=title, url=url)
        session.add(item)
        session.commit()
        session.refresh(item)
        card = Card(item_id=item.id, summary="s")
        session.add(card)
        session.commit()
        session.refresh(card)
        return card.id, item.id


def fake_fetch(markdown: str = "# Body", status: str = "ok"):
    """A fetcher stub matching documents.fetch_fulltext's return shape."""
    def fetcher(url: str) -> dict:
        return {"markdown": markdown, "content_type": "text/html", "status": status,
                "error": None, "source_url": url}
    return fetcher


def test_fetch_card_fulltext_stores_and_returns_status(tmp_path: Path) -> None:
    """Fetching a card's full text stores the markdown and reports the status."""
    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(engine)
    result = fetch_card_fulltext(engine, card_id, fetcher=fake_fetch("# Body"))
    assert result["status"] == "ok"
    assert result["text_chars"] == len("# Body")
    assert get_fulltext(engine, item_id)["markdown"] == "# Body"


def test_fetch_card_fulltext_unknown_card_returns_none(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    assert fetch_card_fulltext(engine, 999, fetcher=fake_fetch()) is None


def test_fetch_card_fulltext_stores_structured_failure_fields(tmp_path: Path) -> None:
    """The on-demand per-card fetch also threads the structured failure
    fields through to the stored Content row (same as the automatic enrich path)."""
    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(engine)

    def fetcher(url: str) -> dict:
        return {
            "markdown": "", "content_type": "", "status": "failed",
            "error": "blocked at T0 (HTTP 403)", "source_url": url,
            "detected_type": "html", "tier_reached": "T0",
            "http_status": 403, "error_class": "blocked",
        }

    fetch_card_fulltext(engine, card_id, fetcher=fetcher)
    stored = get_fulltext(engine, item_id)
    assert stored["detected_type"] == "html"
    assert stored["tier_reached"] == "T0"
    assert stored["http_status"] == 403
    assert stored["error_class"] == "blocked"


def test_store_card_markdown_stores_provided_text_directly(tmp_path: Path) -> None:
    """Claude sessions can store text they obtained themselves (e.g. a YouTube
    transcript via the yt-transcribe command) without the service re-fetching."""
    from spyglass_service.fulltext import store_card_markdown

    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(engine)
    result = store_card_markdown(engine, card_id, "# Transcript\n\nwords")
    assert result["status"] == "ok"
    assert get_fulltext(engine, item_id)["markdown"] == "# Transcript\n\nwords"
    assert store_card_markdown(engine, 999, "x") is None


def test_truncated_title_is_repaired_from_the_page(tmp_path: Path) -> None:
    """Raindrop saves ellipsis-truncated titles; fetching the full text repairs
    the item title from the page when it plausibly completes the saved one."""
    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(
        engine, title="Chronos: Temporal-Aware Conversational Agents with Structured..."
    )
    full = "Chronos: Temporal-Aware Conversational Agents with Structured Memory"
    result = fetch_card_fulltext(
        engine, card_id, fetcher=fake_fetch(), title_fetcher=lambda url: full
    )
    assert result["title"] == full
    with Session(engine) as session:
        assert session.get(Item, item_id).title == full


def test_intact_titles_are_never_touched(tmp_path: Path) -> None:
    """No ellipsis, no repair: the title fetcher is not even called."""
    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(engine, title="A complete title")
    calls: list[str] = []

    def spy(url: str) -> str:
        calls.append(url)
        return "Something else entirely"

    fetch_card_fulltext(engine, card_id, fetcher=fake_fetch(), title_fetcher=spy)
    assert calls == []
    with Session(engine) as session:
        assert session.get(Item, item_id).title == "A complete title"


def test_repair_rejects_titles_that_do_not_complete_the_saved_one(tmp_path: Path) -> None:
    """A page title that does not extend the truncated prefix is not trusted."""
    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(engine, title="Chronos: Temporal-Aware Agents...")
    fetch_card_fulltext(
        engine, card_id, fetcher=fake_fetch(), title_fetcher=lambda url: "404 Not Found"
    )
    with Session(engine) as session:
        assert session.get(Item, item_id).title == "Chronos: Temporal-Aware Agents..."


def test_repair_strips_arxiv_id_prefixes(tmp_path: Path) -> None:
    """arXiv abs pages title as "[2602.05638] Real Title"; the id is dropped."""
    engine = make_engine(tmp_path)
    card_id, item_id = seed_card(engine, title="SurgMotion: A Video-Native Foundation…")
    fetch_card_fulltext(
        engine,
        card_id,
        fetcher=fake_fetch(),
        title_fetcher=lambda url: "[2602.05638] SurgMotion: A Video-Native Foundation Model",
    )
    with Session(engine) as session:
        assert session.get(Item, item_id).title == "SurgMotion: A Video-Native Foundation Model"
