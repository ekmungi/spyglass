# ruff: noqa: F811
"""Tests for feed kind filtering of unjudged items, de-duplicated related items and the reader's note."""

from sqlmodel import Session

from spyglass_service.models import Item
from spyglass_service.radar.models import ItemState

from spyglass_service.radar.api.item_quality import address_key, address_kind, title_key

from .test_items_api import StubIndex, StubState, add_item, env, ids  # noqa: F401


def _mark_from_user(engine, item_id: int, note: str | None = None) -> None:
    """Mark an item as sent in by the reader, optionally with a note."""
    with Session(engine) as session:
        session.add(ItemState(item_id=item_id, from_user=True, user_note=note))
        session.commit()


# --- kind filter -------------------------------------------------------------------------------


def test_kind_filter_includes_unjudged_items_whose_address_says_what_they_are(env) -> None:
    _, engine, client = env
    paper = add_item(engine, 1, tier=None, url="https://arxiv.org/abs/2611.00001")
    doi = add_item(engine, 2, tier=None, url="https://doi.org/10.1000/abc")
    video = add_item(engine, 3, tier=None, url="https://www.youtube.com/watch?v=abc")
    short = add_item(engine, 4, tier=None, url="https://youtu.be/abc")
    repo = add_item(engine, 5, tier=None, url="https://github.com/acme/tool")
    news = add_item(engine, 6, tier=None, url="https://news.example/story")
    judged = add_item(engine, 7, tier="notable", kind="paper", url="https://journal.example/p")
    assert set(ids(client.get("/api/radar/feed?kind=paper"))) == {paper, doi, judged}
    assert set(ids(client.get("/api/radar/feed?kind=video"))) == {video, short}
    assert set(ids(client.get("/api/radar/feed?kind=tool"))) == {repo}
    assert news not in ids(client.get("/api/radar/feed?kind=paper"))


def test_kind_filter_does_not_infer_a_kind_for_a_judged_item(env) -> None:
    _, engine, client = env
    add_item(engine, 1, tier="notable", kind="news", url="https://arxiv.org/abs/2611.00001")
    assert ids(client.get("/api/radar/feed?kind=paper")) == []


def test_from_you_papers_lists_unjudged_arxiv_submissions_with_the_inferred_kind(env) -> None:
    _, engine, client = env
    first = add_item(engine, 1, tier=None, url="https://arxiv.org/abs/2611.00001")
    second = add_item(engine, 2, tier=None, url="https://arxiv.org/abs/2611.00002")
    other = add_item(engine, 3, tier=None, url="https://news.example/story")
    for item_id in (first, second, other):
        _mark_from_user(engine, item_id)
    body = client.get("/api/radar/feed?from_user=true&kind=paper").json()
    assert {i["id"] for i in body["items"]} == {first, second} and body["total"] == 2
    assert {i["kind"] for i in body["items"]} == {"paper"}


def test_unjudged_items_show_the_kind_their_address_implies(env) -> None:
    _, engine, client = env
    paper = add_item(engine, 1, tier=None, url="https://arxiv.org/abs/2611.00001")
    plain = add_item(engine, 2, tier=None, url="https://news.example/story")
    kinds = {i["id"]: i["kind"] for i in client.get("/api/radar/feed?tier=unjudged").json()["items"]}
    assert kinds[paper] == "paper" and kinds[plain] == "news"


# --- related and story sources -----------------------------------------------------------------


def test_related_items_are_unique_by_address_and_title_and_exclude_the_item_itself(env) -> None:
    app, engine, client = env
    main = add_item(engine, 1, url="https://news.example/story")
    first = add_item(engine, 2, title="Same story", url="https://other.example/a?utm_source=x")
    same_url = add_item(engine, 3, title="A different title", url="https://www.other.example/a/")
    same_title = add_item(engine, 4, title="  Same   Story ", url="https://third.example/b")
    unique = add_item(engine, 5, title="Another story", url="https://fourth.example/c")
    itself = add_item(engine, 6, title="Item 1 again", url="https://news.example/story/")
    app.state.service_state = StubState(StubIndex([first, same_url, same_title, itself, unique]))
    related = client.get(f"/api/radar/items/{main}").json()["related"]
    assert [r["id"] for r in related] == [first, unique]


def _set_origin(engine, item_id: int, origin: str) -> None:
    """Give an item a publication name."""
    with Session(engine) as session:
        session.get(Item, item_id).origin = origin
        session.commit()


def test_story_sources_are_unique_by_address_and_publication(env) -> None:
    _, engine, client = env
    main = add_item(engine, 1, event_key="deal", url="https://news.example/story")
    first = add_item(engine, 2, event_key="deal", url="https://pub-one.example/a")
    same_pub = add_item(engine, 3, event_key="deal", url="https://pub-one.example/b")
    second = add_item(engine, 4, event_key="deal", url="https://pub-two.example/x?utm_campaign=y")
    same_url = add_item(engine, 5, event_key="deal", url="https://www.pub-two.example/x")
    own = add_item(engine, 6, event_key="deal", url="https://news.example/story/")
    for item_id, name in ((first, "Pub One"), (same_pub, "pub one"), (second, "Pub Two"), (same_url, "Pub Three"),
                          (own, "Pub Four")):
        _set_origin(engine, item_id, name)
    sources = client.get(f"/api/radar/items/{main}").json()["story_sources"]
    assert [s["item_id"] for s in sources] == [first, second]


def test_story_sources_without_a_publication_name_are_not_merged_by_name(env) -> None:
    _, engine, client = env
    main = add_item(engine, 1, event_key="deal")
    one = add_item(engine, 2, event_key="deal", url="https://a.example/1")
    two = add_item(engine, 3, event_key="deal", url="https://b.example/2")
    sources = client.get(f"/api/radar/items/{main}").json()["story_sources"]
    assert [s["item_id"] for s in sources] == [one, two]


# --- the reader's note -------------------------------------------------------------------------


def test_detail_returns_the_readers_own_note(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1, tier=None, url="https://arxiv.org/abs/2611.00001")
    _mark_from_user(engine, item_id, note="Check the ablation table")
    assert client.get(f"/api/radar/items/{item_id}").json()["user_note"] == "Check the ablation table"


def test_detail_user_note_is_null_without_a_note(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    assert client.get(f"/api/radar/items/{item_id}").json()["user_note"] is None


# --- helpers -----------------------------------------------------------------------------------


def test_address_key_ignores_scheme_www_fragment_trailing_slash_and_tracking() -> None:
    assert address_key("HTTPS://www.Example.com/a/b/?utm_source=x&id=7#top") == "example.com/a/b?id=7"
    assert address_key("http://example.com/a") == address_key("https://www.example.com/a/")
    assert address_key("") == ""


def test_title_key_and_address_kind() -> None:
    assert title_key("  Hello,   WORLD! ") == "hello world"
    assert address_kind("https://www.youtube.com/watch?v=1") == "video"
    assert address_kind("https://news.example/x") is None
