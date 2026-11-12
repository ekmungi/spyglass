"""Tests for the browser extension's direct import route (`POST /import/direct`) and its check route.

The route skips the confirmation window, so it needs the per-install key, a size limit, a rate
limit and the same address checks as every other import. No test touches the network.
"""

import logging
import socket
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.content_store import get_fulltext
from spyglass_service.models import Item
from spyglass_service.radar import netguard
from spyglass_service.radar.api import import_direct as direct_api
from spyglass_service.radar.import_direct import RateLimiter
from spyglass_service.radar.import_key import button_key
from spyglass_service.radar.models import ItemState, ReaderDoc
from spyglass_service.request_guards import CrossSiteGuard

from .test_importer import PAGE, URL
from .test_sources_support import make_engine

DIRECT = "/api/radar/import/direct"
CHECK = DIRECT + "/check"
EXTENSION = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
BAD_KEY = "The key is missing or wrong."
SELECTION = " ".join(f"Selected sentence {n} says something specific about the trial." for n in range(12))


class FakeScheduler:
    """Counts the requests to judge the new item now."""

    def __init__(self) -> None:
        self.kicks = 0

    def kick_assessment(self) -> bool:
        self.kicks += 1
        return True


def longer_page(sentences: int) -> str:
    """The shared test page with a longer body, so its word count differs."""
    body = " ".join(f"Sentence {n} explains the new results from the trial in plain words." for n in range(sentences))
    return f"<html><head><title>Trial results are in</title></head><body><article><h1>Trial results are in</h1><p>{body}</p></article></body></html>"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any lookup, connection or HTTP request during an import fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("the import path must not use the network")

    monkeypatch.setattr(netguard, "resolve", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture()
def env(tmp_path):
    """A small app with only the direct-import router behind the cross-site guard."""
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(direct_api.router, prefix="/api/radar")
    app.add_middleware(CrossSiteGuard)
    app.state.engine = engine
    app.state.settings = SimpleNamespace(data_dir=tmp_path / "data")
    app.state.radar_scheduler = FakeScheduler()
    with TestClient(app, follow_redirects=False) as client:
        yield SimpleNamespace(client=client, engine=engine, app=app, key=button_key(tmp_path / "data"))
    engine.dispose()


def send(env, headers=None, key=True, **body):
    """POST a page the way the extension does (key in the header, JSON body, extension origin)."""
    payload = {"url": URL, "title": "Trial results are in", "html": PAGE, "kind": "page", **body}
    sent = {"Origin": EXTENSION, **({"X-Spyglass-Key": env.key} if key else {}), **(headers or {})}
    return env.client.post(DIRECT, json=payload, headers=sent)


def row(env, model, item_id):
    with Session(env.engine) as session:
        return session.exec(select(model).where(model.item_id == item_id)).first()


def items(env) -> list[Item]:
    with Session(env.engine) as session:
        return list(session.exec(select(Item)).all())


# --- the key ---------------------------------------------------------------------------------


@pytest.mark.parametrize("supplied", [None, "", "short", "0" * 32, "G" * 32, "0" * 31 + "x"])
def test_a_missing_or_wrong_key_is_refused_without_importing_anything(env, supplied) -> None:
    headers = {} if supplied is None else {"X-Spyglass-Key": supplied}
    response = send(env, key=False, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": BAD_KEY}
    assert items(env) == []


def test_a_key_that_is_almost_right_gets_the_same_answer_as_any_other_wrong_key(env) -> None:
    almost = env.key[:-1] + ("0" if env.key[-1] != "0" else "1")
    near = send(env, key=False, headers={"X-Spyglass-Key": almost})
    far = send(env, key=False, headers={"X-Spyglass-Key": "f" * 32})
    assert (near.status_code, near.json()) == (far.status_code, far.json()) == (403, {"detail": BAD_KEY})


def test_the_key_is_not_accepted_in_the_body_or_the_query(env) -> None:
    by_body = env.client.post(DIRECT, json={"url": URL, "html": PAGE, "key": env.key}, headers={"Origin": EXTENSION})
    by_query = env.client.post(DIRECT + f"?key={env.key}", json={"url": URL, "html": PAGE})
    assert by_body.status_code == by_query.status_code == 403


def test_the_check_route_answers_to_the_right_key_only(env) -> None:
    assert env.client.get(CHECK).status_code == 403
    assert env.client.get(CHECK, headers={"X-Spyglass-Key": "0" * 32}).json() == {"detail": BAD_KEY}
    good = env.client.get(CHECK, headers={"X-Spyglass-Key": env.key, "Origin": EXTENSION})
    assert good.status_code == 200 and good.json()["ok"] is True and good.json()["app"] == "spyglass"
    assert items(env) == []


def test_a_new_key_disconnects_the_old_one(env, tmp_path) -> None:
    from spyglass_service.radar.import_key import rotate_button_key

    rotate_button_key(tmp_path / "data")
    assert send(env).status_code == 403


# --- a page ----------------------------------------------------------------------------------


def test_a_page_becomes_a_from_you_item_sent_by_the_extension(env) -> None:
    response = send(env, note="Relevant for the screening project")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"item_id", "title", "words", "replaced"}
    assert body["title"] == "Trial results are in" and body["words"] > 200 and body["replaced"] is False
    item_id = body["item_id"]
    state = row(env, ItemState, item_id)
    assert state.from_user is True and state.captured_via == "extension"
    assert state.user_note == "Relevant for the screening project"
    doc = row(env, ReaderDoc, item_id)
    assert doc.status == "ok" and "Sentence 29 explains" in doc.html and "<script" not in doc.html
    assert "reader@example.com" not in doc.html and "reader@example.com" not in get_fulltext(env.engine, item_id)["markdown"]
    assert env.app.state.radar_scheduler.kicks == 1


def test_no_note_leaves_the_reader_note_empty(env) -> None:
    item_id = send(env).json()["item_id"]
    assert row(env, ItemState, item_id).user_note is None


def test_a_page_from_the_text_field_is_accepted_too(env) -> None:
    response = send(env, html=None, text="A short paragraph about the trial. " * 20)
    assert response.status_code == 200 and response.json()["words"] >= 100


@pytest.mark.parametrize("body", [
    {"html": None},                                    # neither html nor text
    {"html": PAGE, "text": "also text"},               # both
    {"title": "t" * 301},
    {"note": "n" * 501},
    {"kind": "everything"},
    {"url": ""},
    {"html": "<html><body><script>x()</script></body></html>"},  # nothing readable
])
def test_malformed_requests_are_refused_with_a_plain_message(env, body) -> None:
    response = send(env, **body)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert items(env) == []


def test_a_body_that_is_not_json_is_refused(env) -> None:
    response = env.client.post(DIRECT, content="not json", headers={"X-Spyglass-Key": env.key, "Content-Type": "application/json"})
    assert response.status_code == 400
    plain = env.client.post(DIRECT, content="{}", headers={"X-Spyglass-Key": env.key, "Content-Type": "text/plain"})
    assert plain.status_code == 415


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///C:/Windows/win.ini", "http://localhost:7778/",
                                 "http://127.0.0.1/", "http://192.168.1.4/a", "http://[::1]/",
                                 "https://user:pw" "@news.example.com/", "http://intranet.local/x", "ftp://news.example.com/a"])
def test_addresses_that_are_not_public_http_are_refused_without_any_network_call(env, url) -> None:
    response = send(env, url=url)
    assert response.status_code == 400
    assert items(env) == []


# --- sizes -----------------------------------------------------------------------------------


def test_a_page_over_six_megabytes_is_refused(env) -> None:
    response = send(env, html="<p>" + "x" * (6 * 1024 * 1024) + "</p>")
    assert response.status_code == 413 and "6 MB" in response.json()["detail"]
    assert items(env) == []


def stub_import(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace the import itself, so a test of the route's limits does not pay for extraction."""
    calls: list[dict] = []

    def fake(engine, settings, **kwargs) -> dict:
        calls.append(kwargs)
        return {"item_id": len(calls), "title": "t", "words": 1, "replaced": False}

    monkeypatch.setattr(direct_api, "import_direct", fake)
    return calls


def test_text_over_two_megabytes_is_refused_but_a_large_page_is_not(env, monkeypatch) -> None:
    calls = stub_import(monkeypatch)
    refused = send(env, html=None, text="word " * (2 * 1024 * 1024 // 5 + 10), kind="selection")
    assert refused.status_code == 413 and "2 MB" in refused.json()["detail"]
    assert calls == []
    big = "<html><body><article>" + "<p>Sentence about the trial results here.</p>" * 70000 + "</article></body></html>"
    assert 2 * 1024 * 1024 < len(big) < 6 * 1024 * 1024
    assert send(env, html=big).status_code == 200 and len(calls) == 1


def test_a_body_far_past_the_limit_is_refused_before_it_is_parsed(env) -> None:
    response = env.client.post(DIRECT, content=b"{" + b"a" * (14 * 1024 * 1024), headers={
        "X-Spyglass-Key": env.key, "Content-Type": "application/json"})
    assert response.status_code == 413


# --- a selection -----------------------------------------------------------------------------


def test_a_selection_on_a_new_address_becomes_the_document_of_that_address(env) -> None:
    response = send(env, kind="selection", html=None, text=SELECTION)
    assert response.status_code == 200
    item_id = response.json()["item_id"]
    with Session(env.engine) as session:
        item = session.get(Item, item_id)
    assert item.url == URL and item.title == "Selection from: Trial results are in"
    assert "Selected sentence 11" in row(env, ReaderDoc, item_id).html


def test_a_selection_may_arrive_as_html(env) -> None:
    fragment = "<h2>Findings</h2><p>" + SELECTION + "</p>"
    response = send(env, kind="selection", html=fragment)
    assert response.status_code == 200
    assert "Selected sentence 3" in row(env, ReaderDoc, response.json()["item_id"]).html


def test_a_selection_never_replaces_a_full_article(env) -> None:
    page_id = send(env).json()["item_id"]
    full_html = row(env, ReaderDoc, page_id).html
    response = send(env, kind="selection", html=None, text=SELECTION)
    assert response.status_code == 200
    selection_id = response.json()["item_id"]
    assert selection_id != page_id
    assert row(env, ReaderDoc, page_id).html == full_html
    with Session(env.engine) as session:
        separate = session.get(Item, selection_id)
    assert separate.url.startswith(URL + "?spyglass_selection=")
    assert "Selected sentence 5" in row(env, ReaderDoc, selection_id).html


def test_the_same_selection_sent_twice_is_one_separate_item(env) -> None:
    send(env)
    first = send(env, kind="selection", html=None, text=SELECTION).json()["item_id"]
    second = send(env, kind="selection", html=None, text=SELECTION).json()["item_id"]
    assert first == second


def test_a_selection_is_attached_to_an_item_whose_document_failed(env) -> None:
    with Session(env.engine) as session:
        item = Item(source="rss", external_id="x1", title="Trial results are in", url=URL, origin="News")
        session.add(item)
        session.flush()
        item_id = item.id
        session.add(ReaderDoc(item_id=item_id, status="failed", error="HTTP 403", html=""))
        session.commit()
    response = send(env, kind="selection", html=None, text=SELECTION)
    assert response.json()["item_id"] == item_id
    assert row(env, ReaderDoc, item_id).status == "ok"


# --- replacing a copy ------------------------------------------------------------------------


def test_a_page_replaces_an_earlier_copy_only_when_it_has_more_words(env) -> None:
    first = send(env, html=longer_page(20)).json()
    assert first["replaced"] is False
    longer = send(env, html=longer_page(60)).json()
    assert longer["item_id"] == first["item_id"] and longer["replaced"] is True and longer["words"] > first["words"]
    shorter = send(env, html=longer_page(20)).json()
    assert shorter["item_id"] == first["item_id"] and shorter["replaced"] is False
    assert shorter["words"] == longer["words"]
    assert "Sentence 59 explains" in row(env, ReaderDoc, first["item_id"]).html


def test_a_page_replaces_a_selection_copy_because_it_has_more_words(env) -> None:
    selected = send(env, kind="selection", html=None, text=SELECTION).json()
    page = send(env).json()
    assert page["item_id"] == selected["item_id"] and page["replaced"] is True


def test_a_kept_copy_still_gets_the_new_note(env) -> None:
    item_id = send(env, html=longer_page(60)).json()["item_id"]
    send(env, html=longer_page(20), note="Second thoughts")
    assert row(env, ItemState, item_id).user_note == "Second thoughts"


# --- the rate limit and the log --------------------------------------------------------------


def test_the_thirty_first_import_in_ten_minutes_is_refused(env, monkeypatch) -> None:
    stub_import(monkeypatch)
    for number in range(30):
        assert send(env, url=f"https://news.example.com/story-{number}").status_code == 200
    blocked = send(env, url="https://news.example.com/story-31")
    assert blocked.status_code == 429 and "too many" in blocked.json()["detail"].lower()


def test_requests_with_a_wrong_key_do_not_use_up_the_limit(env) -> None:
    for _ in range(40):
        send(env, key=False)
    assert send(env).status_code == 200


def test_the_rate_limiter_forgets_old_imports() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])
    assert limiter.allow() and limiter.allow() and not limiter.allow()
    now[0] = 10.5
    assert limiter.allow()


def test_each_import_is_logged_as_one_line_without_content_or_key(env, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="spyglass_service.radar.api.import_direct"):
        send(env, note="private thoughts")
    lines = [r.getMessage() for r in caplog.records if r.name.endswith("import_direct")]
    assert len(lines) == 1 and "news.example.com" in lines[0]
    assert "Sentence" not in lines[0] and "private thoughts" not in lines[0] and env.key not in lines[0]
