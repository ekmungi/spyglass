"""Tests for the shared RadarItem shape: titles reach the interface as plain text."""

import pytest
from sqlmodel import Session

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.serialize import radar_items


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database."""
    eng = create_db_engine(tmp_path / "t.db")
    init_db(eng)
    yield eng
    eng.dispose()


def _add(engine, title: str, headline: str | None = None) -> int:
    """Insert an item (and, with a headline, its assessment); return the id."""
    with Session(engine) as session:
        item = Item(source="news", external_id=title, title=title, url="https://example.org/a")
        session.add(item)
        session.commit()
        if headline is not None:
            session.add(Assessment(item_id=item.id, stage="digest", score=60, tier="notable",
                                   section="industry", kind="news", headline=headline))
            session.commit()
        return item.id


def test_markup_and_entities_are_removed_from_title_and_headline(engine) -> None:
    """A feed title that arrived as an anchor tag is shown as its text, entities decoded."""
    item_id = _add(engine, '<a href="https://news.example/x">Oura to acquire Counsel Health</a>')
    other = _add(engine, "Q&amp;A: Tom &amp; Jerry &#39;AI&#39; <b>deal</b>")
    with Session(engine) as session:
        first, second = radar_items(session, [item_id, other])
    assert first["title"] == "Oura to acquire Counsel Health" == first["headline"]
    assert second["title"] == "Q&A: Tom & Jerry 'AI' deal" == second["headline"]


def test_a_rewritten_headline_is_cleaned_too_and_plain_titles_are_untouched(engine) -> None:
    """The model's headline is plain already; cleaning must not change ordinary text."""
    item_id = _add(engine, "A plain title", headline="Fish &amp; chips <i>rise</i>")
    with Session(engine) as session:
        (row,) = radar_items(session, [item_id])
    assert row["title"] == "A plain title" and row["headline"] == "Fish & chips rise"


def test_no_ids_gives_no_items(engine) -> None:
    """An empty request returns an empty list without querying."""
    with Session(engine) as session:
        assert radar_items(session, []) == []
