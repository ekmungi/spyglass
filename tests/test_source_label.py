"""Tests for the card source label: the Feeds-tab name the user set wins over the feed's own title."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.content_store import store_fulltext
from spyglass_service.models import Card, Feed, Item
from spyglass_service.source_label import display_origin, user_feed_names

# A feed whose own title is the raw arXiv query, renamed by the user in the Feeds tab.
NAMED_URL = "https://export.arxiv.org/api/query?search_query=surgery"
RAW_TITLE = "ArXiv Query: search_query=surgery&id_list=&start=0&max_results=100"
USER_NAME = "arXiv: surgery and endoscopy AI"
# A feed Spyglass named by itself (the bare site address), never renamed by the user.
UNNAMED_URL = "https://developer.nvidia.com/blog/feed/"


def make_client(tmp_path: Path) -> TestClient:
    """A TestClient over a fresh data dir, with the startup embed pass off."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, skip_startup_embed=True))


def add_feed(session: Session, url: str, name: str, *, overridden: bool) -> None:
    """Insert one Feed row with the given name and whether the user set it."""
    session.add(Feed(feed_url=url, name=name, name_overridden=overridden, kind="rss",
                     added_via="manual"))
    session.commit()


def add_card(session: Session, external_id: str, *, feed_url: str | None, origin: str | None) -> int:
    """Insert an item (with its stored origin) and its card; return the card id."""
    item = Item(source="rss", external_id=external_id, title=f"Paper {external_id}",
                url=f"https://x.test/{external_id}", feed_url=feed_url, origin=origin)
    session.add(item)
    session.commit()
    session.refresh(item)
    card = Card(item_id=item.id, summary="s")
    session.add(card)
    session.commit()
    session.refresh(card)
    return card.id


def seed_three(client: TestClient) -> dict[str, int]:
    """One card each from a user-named feed, a self-named feed, and no feed at all."""
    with Session(client.app.state.engine) as session:
        add_feed(session, NAMED_URL, USER_NAME, overridden=True)
        add_feed(session, UNNAMED_URL, "developer.nvidia.com", overridden=False)
        return {
            "named": add_card(session, "n1", feed_url=NAMED_URL, origin=RAW_TITLE),
            "unnamed": add_card(session, "u1", feed_url=UNNAMED_URL, origin="NVIDIA Technical Blog"),
            "nofeed": add_card(session, "r1", feed_url=None, origin="github.com"),
        }


# --- the helper ---------------------------------------------------------------------------

def test_user_feed_names_keeps_only_names_the_user_set(tmp_path: Path) -> None:
    """Self-filled names and blank user names are left out of the map."""
    with make_client(tmp_path) as client, Session(client.app.state.engine) as session:
        add_feed(session, NAMED_URL, USER_NAME, overridden=True)
        add_feed(session, UNNAMED_URL, "developer.nvidia.com", overridden=False)
        add_feed(session, "https://blank.test/feed", "   ", overridden=True)
        names = user_feed_names(session)
    assert names == {NAMED_URL: USER_NAME}


def test_display_origin_prefers_the_user_name_then_the_stored_origin() -> None:
    """A named feed's item shows the name; any other item keeps its stored origin."""
    names = {NAMED_URL: USER_NAME}
    named = Item(source="rss", external_id="a", title="t", url="u", feed_url=NAMED_URL, origin=RAW_TITLE)
    unnamed = Item(source="rss", external_id="b", title="t", url="u", feed_url=UNNAMED_URL, origin="NVIDIA")
    nofeed = Item(source="raindrop", external_id="c", title="t", url="u", feed_url=None, origin=None)
    assert display_origin(named, names) == USER_NAME
    assert display_origin(unnamed, names) == "NVIDIA"
    assert display_origin(nofeed, names) is None


# --- the views --------------------------------------------------------------------------

def test_cards_list_shows_the_user_feed_name(tmp_path: Path) -> None:
    """The list labels a named feed's card with the user's name and leaves the others alone."""
    with make_client(tmp_path) as client:
        ids = seed_three(client)
        by_id = {c["id"]: c for c in client.get("/api/cards").json()}
    assert by_id[ids["named"]]["origin"] == USER_NAME
    assert by_id[ids["unnamed"]]["origin"] == "NVIDIA Technical Blog"
    assert by_id[ids["nofeed"]]["origin"] == "github.com"


def test_single_card_and_update_show_the_user_feed_name(tmp_path: Path) -> None:
    """The reader's single-card fetch and a card update return the same label as the list."""
    with make_client(tmp_path) as client:
        ids = seed_three(client)
        one = client.get(f"/api/cards/{ids['named']}").json()
        patched = client.patch(f"/api/cards/{ids['named']}", json={"note": "keep"}).json()
    assert one["origin"] == USER_NAME
    assert patched["origin"] == USER_NAME


def test_search_results_show_the_user_feed_name(tmp_path: Path) -> None:
    """Full-text search labels its hits the same way as the list."""
    with make_client(tmp_path) as client:
        ids = seed_three(client)
        engine = client.app.state.engine
        with Session(engine) as session:
            item_id = session.get(Card, ids["named"]).item_id
        store_fulltext(engine, item_id=item_id, markdown="Laparoscopic instrument tracking.",
                       source_url="u", content_type="text/html", status="ok")
        results = client.get("/api/search", params={"q": "laparoscopic"}).json()
    assert [r["origin"] for r in results] == [USER_NAME]


def test_renaming_a_feed_relabels_its_existing_cards(tmp_path: Path) -> None:
    """A rename through the Feeds API changes the label of cards collected before it."""
    with make_client(tmp_path) as client:
        ids = seed_three(client)
        with Session(client.app.state.engine) as session:
            feed_id = session.exec(select(Feed).where(Feed.feed_url == UNNAMED_URL)).one().id
        client.patch(f"/api/feeds/{feed_id}", json={"name": "NVIDIA blog"})
        card = client.get(f"/api/cards/{ids['unnamed']}").json()
    assert card["origin"] == "NVIDIA blog"


def test_new_brief_reference_line_uses_the_user_feed_name(tmp_path: Path) -> None:
    """A brief composed now names the source by the user's feed name in its reference line."""
    from datetime import UTC, datetime

    import numpy as np

    from spyglass_service.brief_narrative import narrative_and_markdown
    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.embeddings import EmbeddingIndex

    engine = create_db_engine(tmp_path / "brief.db")
    init_db(engine)
    index = EmbeddingIndex(lambda texts: np.ones((len(texts), 4), np.float32), "fake", 4)
    with Session(engine) as session:
        add_feed(session, NAMED_URL, USER_NAME, overridden=True)
        session.add(Item(id=1, source="rss", external_id="1", title="Featured F",
                         url="https://x.test/1", feed_url=NAMED_URL, origin=RAW_TITLE))
        session.flush()
        session.add(Card(id=1, item_id=1, summary="s", relevance_score=85,
                         relevance_at=datetime(2026, 11, 10, tzinfo=UTC)))
        session.commit()

    def llm(messages):
        return {"lead": "Lead.", "sections": [{"heading": "Theme", "bullets": ["Cites [1]."]}]}

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with Session(engine) as session:
        featured = [(session.get(Card, 1), session.get(Item, 1))]
        markdown = narrative_and_markdown(engine, index, settings, featured, [], llm)
    assert f"[Featured F](card:1) — {USER_NAME}, " in markdown
    assert RAW_TITLE not in markdown
