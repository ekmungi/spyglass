"""Tests for the radar items API: feed filters and paging, item detail, PDF, signals, save, vote."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.content_store import store_fulltext
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Feed, Item
from spyglass_service.radar.api import items as items_api
from spyglass_service.radar.models import (
    Assessment, AssistThread, ItemExtra, ItemState, ReaderDoc, Signal, dumps,
)
from spyglass_service.radar.reader.pdf import PdfError

NOW = datetime.now(UTC).replace(tzinfo=None)


class StubIndex:
    """An embedding index whose neighbours are fixed."""

    def __init__(self, neighbours: list[int]) -> None:
        self.neighbours = neighbours

    def similar(self, item_id: int, k: int = 5) -> list[tuple[int, float]]:
        return [(i, 0.9) for i in self.neighbours][:k]


class StubState:
    """Stands in for the app's service state."""

    def __init__(self, index) -> None:
        self.index = index

    def ensure_index(self):
        if isinstance(self.index, Exception):
            raise self.index
        return self.index


@pytest.fixture()
def env(tmp_path):
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    app = FastAPI()
    app.include_router(items_api.router, prefix="/api/radar")
    app.state.engine = engine
    app.state.settings = Settings(data_dir=tmp_path)
    app.state.service_state = StubState(StubIndex([]))
    yield app, engine, TestClient(app)
    engine.dispose()


def add_item(engine, n: int, *, tier: str | None = "notable", age_hours: float = 1, section: str = "models",
             kind: str = "news", title: str | None = None, feed_url: str | None = None,
             published: bool = True, event_key: str | None = None, url: str | None = None,
             fetched_age_hours: float | None = None) -> int:
    """Insert an item, with an assessment unless `tier` is None."""
    when = NOW - timedelta(hours=age_hours)
    with Session(engine) as session:
        item = Item(source="rss", external_id=f"e{n}", title=title or f"Item {n}", url=url or f"https://x.example/{n}",
                    published_at=when if published else None, feed_url=feed_url,
                    fetched_at=NOW - timedelta(hours=fetched_age_hours if fetched_age_hours is not None else age_hours))
        session.add(item)
        session.commit()
        if tier is not None:
            session.add(Assessment(item_id=item.id, tier=tier, section=section, kind=kind, score=50,
                                   event_key=event_key, key_points=dumps(["a point"]), entities=dumps([])))
            session.commit()
        return item.id


def ids(response) -> list[int]:
    return [i["id"] for i in response.json()["items"]]


# --- feed ------------------------------------------------------------------------------------


def test_feed_default_hides_out_old_unjudged_and_disabled_feeds(env) -> None:
    _, engine, client = env
    with Session(engine) as session:
        session.add(Feed(feed_url="https://off.example/rss", name="Off", kind="rss", enabled=False, added_via="manual"))
        session.add(Feed(feed_url="https://on.example/rss", name="On", kind="rss", enabled=True, added_via="manual"))
        session.commit()
    top = add_item(engine, 1, tier="top")
    skim = add_item(engine, 2, tier="skim", age_hours=5)
    out = add_item(engine, 3, tier="out")
    fresh_unjudged = add_item(engine, 4, tier=None, age_hours=3)
    old_unjudged = add_item(engine, 5, tier=None, age_hours=24 * 5)
    disabled = add_item(engine, 6, tier="top", feed_url="https://off.example/rss")
    enabled = add_item(engine, 7, tier="top", feed_url="https://on.example/rss", age_hours=2)
    body = client.get("/api/radar/feed").json()
    got = [i["id"] for i in body["items"]]
    assert got == [top, enabled, fresh_unjudged, skim]
    assert {out, old_unjudged, disabled}.isdisjoint(got)
    assert body["total"] == 4 and body["next_before"] is None


def test_feed_item_shape_is_a_radar_item(env) -> None:
    _, engine, client = env
    add_item(engine, 1, tier="top", section="health")
    item = client.get("/api/radar/feed").json()["items"][0]
    assert item["tier"] == "top" and item["section"] == "health" and item["key_points"] == ["a point"]
    assert item["state"] == {"saved": False, "opened": False, "vote": None, "from_user": False,
                             "captured_via": None, "vault_path": None}


def test_feed_tier_all_and_explicit_tiers(env) -> None:
    _, engine, client = env
    top = add_item(engine, 1, tier="top")
    out = add_item(engine, 2, tier="out")
    old_unjudged = add_item(engine, 3, tier=None, age_hours=24 * 9)
    assert set(ids(client.get("/api/radar/feed?tier=all"))) == {top, out, old_unjudged}
    assert ids(client.get("/api/radar/feed?tier=out")) == [out]
    assert ids(client.get("/api/radar/feed?tier=unjudged")) == [old_unjudged]


def test_feed_section_and_kind_filters(env) -> None:
    _, engine, client = env
    a = add_item(engine, 1, section="models", kind="news")
    b = add_item(engine, 2, section="health", kind="paper")
    assert ids(client.get("/api/radar/feed?section=health")) == [b]
    assert ids(client.get("/api/radar/feed?kind=news")) == [a]
    assert ids(client.get("/api/radar/feed?section=health&kind=news")) == []


def test_feed_saved_and_from_user_ignore_the_quality_rules(env) -> None:
    _, engine, client = env
    saved_out = add_item(engine, 1, tier="out")
    sent = add_item(engine, 2, tier=None, age_hours=24 * 30)
    plain = add_item(engine, 3, tier="top")
    with Session(engine) as session:
        session.add(ItemState(item_id=saved_out, saved_at=NOW))
        session.add(ItemState(item_id=sent, from_user=True, captured_via="slack"))
        session.commit()
    assert ids(client.get("/api/radar/feed?saved=true")) == [saved_out]
    assert ids(client.get("/api/radar/feed?from_user=true")) == [sent]
    assert plain in ids(client.get("/api/radar/feed"))
    assert saved_out not in ids(client.get("/api/radar/feed"))
    body = client.get("/api/radar/feed?from_user=true").json()["items"][0]
    assert body["state"]["from_user"] is True and body["state"]["captured_via"] == "slack"


def test_feed_filed_lists_items_with_a_filing_place_and_ignores_the_quality_rules(env) -> None:
    _, engine, client = env
    filed_out = add_item(engine, 1, tier="out", age_hours=24 * 30)
    other_extra = add_item(engine, 2, tier="top")
    add_item(engine, 3, tier="top")
    with Session(engine) as session:
        session.add(ItemExtra(item_id=filed_out, data=dumps(
            {"filed": {"path": "01 PROJECTS/A/Note.md", "project": "A", "at": "2026-11-12T10:00:00"}})))
        session.add(ItemExtra(item_id=other_extra, data=dumps({"points": 3})))
        session.commit()
    assert ids(client.get("/api/radar/feed?filed=true")) == [filed_out]
    assert filed_out not in ids(client.get("/api/radar/feed"))  # hidden by the default rules


def test_feed_search_matches_stored_text_and_titles(env) -> None:
    _, engine, client = env
    by_text = add_item(engine, 1, title="Plain title")
    by_title = add_item(engine, 2, title="Quantum gadget unveiled")
    other = add_item(engine, 3, title="Unrelated")
    store_fulltext(engine, item_id=by_text, markdown="This text discusses quantum sensors in depth.")
    assert set(ids(client.get("/api/radar/feed?q=quantum"))) == {by_text, by_title}
    assert other not in ids(client.get("/api/radar/feed?q=QUANTUM"))
    assert client.get("/api/radar/feed?q=quantum").json()["total"] == 2


def test_feed_search_survives_quotes_and_wildcards(env) -> None:
    _, engine, client = env
    add_item(engine, 1, title="100% sure")
    response = client.get('/api/radar/feed', params={"q": '"100% sure'})
    assert response.status_code == 200
    assert client.get("/api/radar/feed", params={"q": "100%"}).json()["total"] == 1
    assert client.get("/api/radar/feed", params={"q": "%"}).json()["total"] == 1


def test_feed_search_hides_out_tier_by_default_but_shows_old_unjudged(env) -> None:
    _, engine, client = env
    out = add_item(engine, 1, tier="out", title="alpha out")
    old = add_item(engine, 2, tier=None, age_hours=24 * 20, title="alpha old")
    assert ids(client.get("/api/radar/feed?q=alpha")) == [old]
    assert set(ids(client.get("/api/radar/feed?q=alpha&tier=all"))) == {out, old}


def test_feed_pages_newest_first_with_a_cursor(env) -> None:
    _, engine, client = env
    created = [add_item(engine, n, age_hours=n) for n in range(1, 8)]  # item n is n hours old
    first = client.get("/api/radar/feed?limit=3").json()
    assert [i["id"] for i in first["items"]] == created[:3]
    assert first["total"] == 7 and first["next_before"]
    second = client.get("/api/radar/feed", params={"limit": 3, "before": first["next_before"]}).json()
    assert [i["id"] for i in second["items"]] == created[3:6]
    third = client.get("/api/radar/feed", params={"limit": 3, "before": second["next_before"]}).json()
    assert [i["id"] for i in third["items"]] == created[6:] and third["next_before"] is None


def test_feed_page_takes_a_whole_run_of_equal_timestamps(env) -> None:
    _, engine, client = env
    same = [add_item(engine, n, published=False, fetched_age_hours=3) for n in range(1, 6)]
    older = add_item(engine, 6, age_hours=10)
    first = client.get("/api/radar/feed?limit=2").json()
    assert sorted(i["id"] for i in first["items"]) == sorted(same)
    second = client.get("/api/radar/feed", params={"limit": 2, "before": first["next_before"]}).json()
    assert [i["id"] for i in second["items"]] == [older]


def test_feed_uses_fetched_at_when_there_is_no_publish_date(env) -> None:
    _, engine, client = env
    late = add_item(engine, 1, published=False, fetched_age_hours=1)
    early = add_item(engine, 2, age_hours=5)
    assert ids(client.get("/api/radar/feed")) == [late, early]


def test_feed_rejects_bad_parameters(env) -> None:
    _, _, client = env
    assert client.get("/api/radar/feed?before=yesterday").status_code == 422
    assert client.get("/api/radar/feed?limit=0").status_code == 422
    assert client.get("/api/radar/feed?limit=500").status_code == 422


# --- detail ----------------------------------------------------------------------------------


def test_detail_builds_the_reader_on_first_open_and_adds_context(env, monkeypatch) -> None:
    app, engine, client = env
    main = add_item(engine, 1, tier="top", event_key="big-launch")
    sibling = add_item(engine, 2, tier="notable", event_key="big-launch")
    near_ok = add_item(engine, 3, tier="skim")
    near_out = add_item(engine, 4, tier="out")
    near_unassessed = add_item(engine, 5, tier=None)
    with Session(engine) as session:
        session.add(AssistThread(item_id=main, title="Earlier question"))
        session.commit()
    app.state.service_state = StubState(StubIndex([near_out, near_unassessed, near_ok, sibling]))
    calls: list[tuple] = []

    def fake_ensure(engine_, settings, item_id, *, force=False, **kwargs):
        calls.append((item_id, force))
        with Session(engine_) as session:
            session.add(ReaderDoc(item_id=item_id, kind="article", html="<p>body</p>", status="ok", word_count=1))
            session.commit()
        return {"kind": "article", "html": "<p>body</p>", "title": "T", "byline": None, "site": None,
                "lead_image": None, "word_count": 1, "source_url": "u", "alt_url": None, "status": "ok", "error": None}

    monkeypatch.setattr(items_api, "ensure_reader_doc", fake_ensure)
    detail = client.get(f"/api/radar/items/{main}").json()
    assert calls == [(main, False)]
    assert detail["id"] == main and detail["reader"]["html"] == "<p>body</p>" and detail["has_reader"] is True
    assert "summary" in detail
    assert [r["id"] for r in detail["related"]] == [near_ok, sibling]
    assert detail["story_sources"] == [{"item_id": sibling, "name": detail["story_sources"][0]["name"],
                                         "url": f"https://x.example/{sibling}"}]
    assert [t["title"] for t in detail["threads"]] == ["Earlier question"]
    assert detail["threads"][0]["id"] and detail["threads"][0]["updated_at"]


def test_detail_returns_a_stored_failed_reader_instead_of_erroring(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, kind="article", html="", status="failed", error="HTTP 403",
                              fetched_at=datetime.now(UTC)))
        session.commit()
    detail = client.get(f"/api/radar/items/{item_id}").json()
    assert detail["reader"]["status"] == "failed" and detail["reader"]["error"] == "HTTP 403"
    assert detail["has_reader"] is False


def test_detail_survives_a_broken_embedding_index(env) -> None:
    app, engine, client = env
    item_id = add_item(engine, 1)
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, html="<p>x</p>", status="ok"))
        session.commit()
    app.state.service_state = StubState(RuntimeError("model missing"))
    response = client.get(f"/api/radar/items/{item_id}")
    assert response.status_code == 200 and response.json()["related"] == []


def test_detail_of_a_picture_whose_file_is_gone_shows_a_sentence(env) -> None:
    """A picture sent in whose file is missing reads as a plain sentence, not a broken image."""
    from spyglass_service.radar import from_you_store
    from spyglass_service.radar.import_image import image_fields

    app, engine, client = env
    link = "https://team.slack.com/files/U1/F200/chart.png"
    item_id = add_item(engine, 1, url=link)
    fields = image_fields(link, "chart", None)
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, kind="article", html=fields["html"], lead_image=link,
                              source_url=link, status="ok"))
        session.commit()
    gone = client.get(f"/api/radar/items/{item_id}").json()["reader"]
    assert "<img" not in gone["html"] and "no longer stored" in gone["html"]
    assert not gone["lead_image"]
    from_you_store.put(app.state.settings.data_dir, item_id, b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    kept = client.get(f"/api/radar/items/{item_id}").json()["reader"]
    assert "<img" in kept["html"] and "no longer stored" not in kept["html"]


def test_a_pdf_you_sent_in_is_served_from_its_store_without_any_download(env, monkeypatch) -> None:
    from spyglass_service.radar import from_you_store

    app, engine, client = env
    link = "https://team.slack.com/files/U1/F1/paper.pdf"
    item_id = add_item(engine, 1, url=link)
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, kind="pdf", html="<p>x</p>", alt_url=link))
        session.commit()
    from_you_store.put(app.state.settings.data_dir, item_id, b"%PDF-1.4 mine")

    def refuse(*_a, **_k):
        raise AssertionError("a PDF the reader sent in is never downloaded")

    monkeypatch.setattr(items_api, "ensure_pdf", refuse)
    response = client.get(f"/api/radar/items/{item_id}/pdf")
    assert response.status_code == 200 and response.content == b"%PDF-1.4 mine"
    assert response.headers["content-type"] == "application/pdf"


def test_detail_unknown_item_is_404(env) -> None:
    assert env[2].get("/api/radar/items/999").status_code == 404


def test_refresh_forces_a_rebuild(env, monkeypatch) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    seen: list[bool] = []

    def fake_ensure(engine_, settings, iid, *, force=False, **kwargs):
        seen.append(force)
        return {"kind": "article", "html": "<p>new</p>", "status": "ok"}

    monkeypatch.setattr(items_api, "ensure_reader_doc", fake_ensure)
    response = client.post(f"/api/radar/items/{item_id}/reader/refresh")
    assert response.status_code == 200 and response.json()["html"] == "<p>new</p>" and seen == [True]
    assert client.post("/api/radar/items/999/reader/refresh").status_code == 404


# --- pdf -------------------------------------------------------------------------------------


def test_pdf_is_served_inline_from_the_cache(env) -> None:
    app, engine, client = env
    item_id = add_item(engine, 1, url="https://arxiv.org/abs/2401.00001v1")
    cache = Path(app.state.settings.data_dir) / "pdf_cache"
    cache.mkdir()
    (cache / f"{item_id}.pdf").write_bytes(b"%PDF-1.4 cached")
    response = client.get(f"/api/radar/items/{item_id}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == "inline"
    assert response.content == b"%PDF-1.4 cached"


def test_pdf_downloads_the_stored_alternate_address(env, monkeypatch) -> None:
    app, engine, client = env
    item_id = add_item(engine, 1, url="https://example.org/landing")
    with Session(engine) as session:
        session.add(ReaderDoc(item_id=item_id, kind="pdf", html="<p>x</p>", alt_url="https://example.org/paper.pdf"))
        session.commit()
    requested: list[str] = []

    def fake_ensure(data_dir, iid, url, **kwargs):
        requested.append(url)
        path = Path(data_dir) / "pdf_cache" / f"{iid}.pdf"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"%PDF-1.4 fresh")
        return path

    monkeypatch.setattr(items_api, "ensure_pdf", fake_ensure)
    response = client.get(f"/api/radar/items/{item_id}/pdf")
    assert response.status_code == 200 and requested == ["https://example.org/paper.pdf"]


def test_pdf_for_an_arxiv_item_without_a_reader_doc_uses_the_arxiv_pdf(env, monkeypatch) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1, url="https://arxiv.org/abs/2401.00001v2")
    requested: list[str] = []

    def fake_ensure(data_dir, iid, url, **kwargs):
        requested.append(url)
        raise PdfError("The PDF host answered HTTP 404.")

    monkeypatch.setattr(items_api, "ensure_pdf", fake_ensure)
    response = client.get(f"/api/radar/items/{item_id}/pdf")
    assert requested == ["https://arxiv.org/pdf/2401.00001v2"]
    assert response.status_code == 502 and "404" in response.json()["detail"]


def test_pdf_404_when_the_item_has_no_pdf_or_unknown(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1, url="https://news.example/story")
    assert client.get(f"/api/radar/items/{item_id}/pdf").status_code == 404
    assert client.get("/api/radar/items/999/pdf").status_code == 404


def test_pdf_never_fetches_non_public_addresses(env, monkeypatch) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1, url="http://127.0.0.1/secret.pdf")
    monkeypatch.setattr(items_api, "ensure_pdf", lambda *a, **k: pytest.fail("must not fetch"))
    assert client.get(f"/api/radar/items/{item_id}/pdf").status_code == 404


# --- signals, save, vote -----------------------------------------------------------------------


def test_open_signal_sets_opened_and_counts(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    first = client.post(f"/api/radar/items/{item_id}/signal", json={"kind": "open"})
    client.post(f"/api/radar/items/{item_id}/signal", json={"kind": "open"})
    assert first.status_code == 200 and first.json()["state"]["opened"] is True
    with Session(engine) as session:
        state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).one()
        assert state.open_count == 2 and state.opened_at is not None
        assert len(session.exec(select(Signal).where(Signal.kind == "open")).all()) == 2


def test_dwell_adds_seconds_capped_per_call(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    url = f"/api/radar/items/{item_id}/signal"
    client.post(url, json={"kind": "dwell", "value": 30})
    client.post(url, json={"kind": "dwell", "value": "45"})
    client.post(url, json={"kind": "dwell", "value": 100000})
    with Session(engine) as session:
        assert session.exec(select(ItemState)).one().read_seconds == 30 + 45 + 120
        values = [s.value for s in session.exec(select(Signal).where(Signal.kind == "dwell")).all()]
        assert values == ["30", "45", "120"]


@pytest.mark.parametrize("body", [
    {"kind": "dwell"}, {"kind": "dwell", "value": "abc"}, {"kind": "dwell", "value": -5},
    {"kind": "teleport"}, {}, {"kind": "expand", "value": "x" * 500},
])
def test_signal_validation(env, body) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    assert client.post(f"/api/radar/items/{item_id}/signal", json=body).status_code == 422


def test_expand_signal_is_logged_without_changing_state(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    assert client.post(f"/api/radar/items/{item_id}/signal", json={"kind": "expand", "value": "key points"}).status_code == 200
    with Session(engine) as session:
        assert session.exec(select(Signal)).one().value == "key points"
        assert session.exec(select(ItemState)).one().open_count == 0


def test_signal_unknown_item_404(env) -> None:
    assert env[2].post("/api/radar/items/999/signal", json={"kind": "open"}).status_code == 404


def test_save_and_unsave(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    saved = client.post(f"/api/radar/items/{item_id}/save").json()
    assert saved["saved"] is True and saved["state"]["saved"] is True
    client.post(f"/api/radar/items/{item_id}/save")
    assert ids(client.get("/api/radar/feed?saved=true")) == [item_id]
    unsaved = client.delete(f"/api/radar/items/{item_id}/save").json()
    assert unsaved["saved"] is False and unsaved["state"]["saved"] is False
    assert ids(client.get("/api/radar/feed?saved=true")) == []
    with Session(engine) as session:
        assert [s.kind for s in session.exec(select(Signal).order_by(Signal.id)).all()] == ["save", "save", "unsave"]
    assert client.post("/api/radar/items/999/save").status_code == 404
    assert client.delete("/api/radar/items/999/save").status_code == 404


def test_vote_sets_and_clears(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    url = f"/api/radar/items/{item_id}/vote"
    assert client.post(url, json={"vote": "more"}).json()["state"]["vote"] == "more"
    assert client.post(url, json={"vote": "less"}).json()["vote"] == "less"
    assert client.post(url, json={"vote": None}).json()["state"]["vote"] is None
    with Session(engine) as session:
        assert [s.value for s in session.exec(select(Signal).order_by(Signal.id)).all()] == ["more", "less", "none"]


def test_vote_validation_and_unknown_item(env) -> None:
    _, engine, client = env
    item_id = add_item(engine, 1)
    assert client.post(f"/api/radar/items/{item_id}/vote", json={"vote": "meh"}).status_code == 422
    assert client.post("/api/radar/items/999/vote", json={"vote": "more"}).status_code == 404
