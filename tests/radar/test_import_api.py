"""Tests for the import endpoints, on an app that mounts only the import router behind the
cross-site guard. No test touches the network."""

import re
import socket
from types import SimpleNamespace

import fitz
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar import import_staging, netguard
from spyglass_service.radar.api import importer as importer_api
from spyglass_service.radar.import_key import button_key
from spyglass_service.radar.models import ReaderDoc
from spyglass_service.request_guards import CrossSiteGuard

from .test_importer import PAGE, URL
from .test_sources_support import make_engine

STAGE = "/api/radar/import/stage"
SITE = "https://news.example.com"
CROSS_SITE = {"Origin": SITE, "Sec-Fetch-Site": "cross-site"}
LOCAL = {"Origin": "http://localhost:7778", "Sec-Fetch-Site": "same-origin"}
TOKEN_REDIRECT = re.compile(r"^/#/import\?token=[0-9a-f]{32}$")


class FakeScheduler:
    def __init__(self) -> None:
        self.kicks = 0

    def kick_assessment(self) -> bool:
        self.kicks += 1
        return True


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("the import path must not use the network")

    monkeypatch.setattr(netguard, "resolve", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    # The real network transport; the test client has its own, so it keeps working.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture()
def env(tmp_path):
    engine = make_engine(tmp_path)
    app = FastAPI()
    app.include_router(importer_api.router, prefix="/api/radar")
    app.add_middleware(CrossSiteGuard)
    app.state.engine = engine
    app.state.settings = SimpleNamespace(data_dir=tmp_path / "data")
    app.state.radar_scheduler = FakeScheduler()
    with TestClient(app, follow_redirects=False) as client:
        yield SimpleNamespace(client=client, engine=engine, app=app, staging=tmp_path / "data" / "import_staging",
                              key=button_key(tmp_path / "data"))
    engine.dispose()


def stage_json(env, **body):
    """Stage a page the way the import window does, carrying the button's key."""
    payload = {"url": URL, "title": "Trial results are in", "html": PAGE, "key": env.key, **body}
    return env.client.post(STAGE, json=payload, headers=LOCAL)


def stage_form(env, headers=None, **fields):
    """Post the fields as multipart/form-data, as the bookmark button's hidden form does."""
    client = env.client
    data = {"url": URL, "title": "Trial results are in", "html": PAGE, "key": env.key, **fields}
    return client.post(STAGE, files={key: (None, value) for key, value in data.items()},
                       headers=headers or CROSS_SITE)


def token_of(response) -> str:
    return response.headers["location"].rsplit("=", 1)[1]


def test_the_import_page_stages_json_and_gets_a_token(env) -> None:
    response = stage_json(env, sender=SITE)
    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.json()["token"])


def test_the_form_transport_is_staged_from_another_site_and_redirected_to_the_import_page(env) -> None:
    response = stage_form(env)
    assert response.status_code == 303
    assert TOKEN_REDIRECT.fullmatch(response.headers["location"])
    preview = env.client.get(f"/api/radar/import/staged/{token_of(response)}", headers=LOCAL).json()
    assert preview["sender"] == "news.example.com" and preview["sender_matches"] is True
    assert preview["replaces_existing"] is False


def test_the_redirect_cannot_be_pointed_anywhere_else(env) -> None:
    response = stage_form(env, next="https://evil.example/", redirect="//evil.example",
                          return_to="https://evil.example")
    assert TOKEN_REDIRECT.fullmatch(response.headers["location"])
    response = stage_form(env, headers={**CROSS_SITE, "Host": "evil.example"})
    assert response.headers["location"].startswith("/#/import?")


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://127.0.0.1:7778/api/radar/collect",
                                 "file:///C:/Windows/win.ini", "http://192.168.1.1/"])
def test_a_form_with_a_non_public_address_lands_on_a_fixed_error(env, url: str) -> None:
    response = stage_form(env, url=url)
    assert response.status_code == 303
    assert response.headers["location"] == "/#/import?error=address"
    assert not env.staging.exists() or not any(env.staging.iterdir())


def test_json_with_a_non_public_address_is_refused(env) -> None:
    response = stage_json(env, url="http://localhost/x")
    assert response.status_code == 400
    assert "not accepted" in response.json()["detail"]


@pytest.mark.parametrize("content_type,body", [
    ("text/plain", "url=https://news.example.com/a&html=x"),
    ("application/x-www-form-urlencoded", "url=https%3A%2F%2Fnews.example.com%2Fa&html=x"),
])
def test_other_body_types_are_refused(env, content_type: str, body: str) -> None:
    response = env.client.post(STAGE, content=body, headers={**CROSS_SITE, "Content-Type": content_type})
    assert response.status_code == 415


def test_json_from_another_site_is_refused(env) -> None:
    response = env.client.post(STAGE, json={"url": URL, "html": PAGE, "key": env.key}, headers=CROSS_SITE)
    assert response.status_code == 403


def test_a_body_over_the_cap_is_refused(env, monkeypatch) -> None:
    monkeypatch.setattr(importer_api, "STAGE_FORM_BYTES", 2_000)
    response = stage_form(env)
    assert response.status_code == 303 and response.headers["location"] == "/#/import?error=size"
    monkeypatch.setattr(importer_api, "STAGE_JSON_BYTES", 2_000)
    assert stage_json(env).status_code == 413


def test_repeated_posts_never_keep_more_than_twenty_pages(env) -> None:
    for _ in range(30):
        assert stage_form(env).status_code == 303
    assert len(list(env.staging.glob("*.json"))) == import_staging.MAX_ENTRIES


def test_the_preview_is_sanitised_text_and_never_the_staged_page(env) -> None:
    token = stage_json(env).json()["token"]
    response = env.client.get(f"/api/radar/import/staged/{token}", headers=LOCAL)
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == URL and body["host"] == "news.example.com"
    assert body["title"] == "Trial results are in" and body["word_count"] > 200
    assert body["excerpt"].startswith("Sentence 0") and len(body["excerpt"]) <= 600
    assert body["existing_item_id"] is None and body["sender"] is None
    for raw in ("<script", "onerror", "reader@example.com", "<article", "Log out"):
        assert raw not in response.text


def test_a_hostile_title_is_returned_as_plain_data(env) -> None:
    title = '<img src=x onerror="alert(1)">Breaking'
    token = stage_json(env, title=title).json()["token"]
    body = env.client.get(f"/api/radar/import/staged/{token}", headers=LOCAL).json()
    assert body["title"] == title
    assert env.client.get(f"/api/radar/import/staged/{token}", headers=LOCAL).headers[
        "content-type"].startswith("application/json")


def test_the_preview_says_when_the_item_already_exists(env) -> None:
    with Session(env.engine) as session:
        item = Item(source="rss", external_id="e1", title="Old", url=URL, origin="News")
        session.add(item)
        session.commit()
        item_id = item.id
    token = stage_json(env).json()["token"]
    body = env.client.get(f"/api/radar/import/staged/{token}", headers=LOCAL).json()
    assert body["existing_item_id"] == item_id


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_the_preview_is_refused_to_other_sites(env, site: str) -> None:
    token = stage_json(env).json()["token"]
    response = env.client.get(f"/api/radar/import/staged/{token}", headers={"Sec-Fetch-Site": site})
    assert response.status_code == 403


def test_an_unknown_token_is_404(env) -> None:
    assert env.client.get(f"/api/radar/import/staged/{'0' * 32}", headers=LOCAL).status_code == 404
    assert env.client.get("/api/radar/import/staged/not-a-token", headers=LOCAL).status_code == 404


def test_accept_imports_the_page_once_and_asks_for_analysis(env) -> None:
    token = stage_json(env).json()["token"]
    response = env.client.post(f"/api/radar/import/staged/{token}/accept", headers=LOCAL)
    assert response.status_code == 200
    item = response.json()
    assert item["url"] == URL and item["state"]["from_user"] is True
    assert item["state"]["captured_via"] == "browser" and item["has_reader"] is True
    assert env.app.state.radar_scheduler.kicks == 1
    assert list(env.staging.glob("*")) == []
    again = env.client.post(f"/api/radar/import/staged/{token}/accept", headers=LOCAL)
    assert again.status_code == 404
    with Session(env.engine) as session:
        assert session.exec(select(ReaderDoc)).first().status == "ok"


def test_accept_and_discard_are_refused_from_another_site(env) -> None:
    token = stage_json(env).json()["token"]
    assert env.client.post(f"/api/radar/import/staged/{token}/accept", headers=CROSS_SITE).status_code == 403
    assert env.client.delete(f"/api/radar/import/staged/{token}", headers=CROSS_SITE).status_code == 403
    assert env.client.get(f"/api/radar/import/staged/{token}", headers=LOCAL).status_code == 200


def test_discard_removes_the_page(env) -> None:
    token = stage_json(env).json()["token"]
    assert env.client.delete(f"/api/radar/import/staged/{token}", headers=LOCAL).status_code == 204
    assert env.client.get(f"/api/radar/import/staged/{token}", headers=LOCAL).status_code == 404
    assert env.client.delete(f"/api/radar/import/staged/{token}", headers=LOCAL).status_code == 404
    with Session(env.engine) as session:
        assert session.exec(select(Item)).all() == []


def test_pasted_text_is_imported(env) -> None:
    response = env.client.post("/api/radar/import/text", headers=LOCAL,
                               json={"url": URL, "text": "Trial results\n\nThe text of the article."})
    assert response.status_code == 200
    item = response.json()
    assert item["state"]["captured_via"] == "paste" and item["title"] == "Trial results"
    assert env.app.state.radar_scheduler.kicks == 1


@pytest.mark.parametrize("body,status", [
    ({"url": "http://localhost/", "text": "words"}, 400),
    ({"url": URL, "text": "   "}, 400),
    ({"url": URL}, 422),
])
def test_pasted_text_is_validated(env, body: dict, status: int) -> None:
    assert env.client.post("/api/radar/import/text", headers=LOCAL, json=body).status_code == status


def test_pasted_text_must_be_json_from_this_site(env) -> None:
    form = env.client.post("/api/radar/import/text", headers=LOCAL,
                           files={"url": (None, URL), "text": (None, "words")})
    assert form.status_code == 415
    foreign = env.client.post("/api/radar/import/text", headers=CROSS_SITE, json={"url": URL, "text": "x"})
    assert foreign.status_code == 403


def make_pdf() -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Methods and results")
    data = document.tobytes()
    document.close()
    return data


def test_a_pdf_file_is_imported(env) -> None:
    response = env.client.post("/api/radar/import/file", headers=LOCAL, data={"url": URL},
                               files={"file": ("paper.pdf", make_pdf(), "application/pdf")})
    assert response.status_code == 200
    assert response.json()["state"]["captured_via"] == "file"
    with Session(env.engine) as session:
        assert session.exec(select(ReaderDoc)).first().kind == "pdf"


def test_a_saved_html_file_is_imported(env) -> None:
    response = env.client.post("/api/radar/import/file", headers=LOCAL, data={"url": URL},
                               files={"file": ("story.html", PAGE.encode(), "text/html")})
    assert response.status_code == 200
    assert response.json()["title"] == "Trial results are in"


def test_a_file_of_another_kind_is_refused(env) -> None:
    response = env.client.post("/api/radar/import/file", headers=LOCAL, data={"url": URL},
                               files={"file": ("notes.docx", b"PK\x03\x04", "application/octet-stream")})
    assert response.status_code == 400 and ".pdf" in response.json()["detail"]


def test_a_file_without_an_address_or_file_is_refused(env) -> None:
    assert env.client.post("/api/radar/import/file", headers=LOCAL,
                           files={"file": ("a.html", PAGE.encode(), "text/html")}).status_code == 400
    assert env.client.post("/api/radar/import/file", headers=LOCAL, data={"url": URL},
                           files={"other": (None, "x")}).status_code == 400


def test_a_file_over_the_cap_is_refused(env, monkeypatch) -> None:
    monkeypatch.setattr(importer_api, "FILE_FORM_BYTES", 1_000)
    response = env.client.post("/api/radar/import/file", headers=LOCAL, data={"url": URL},
                               files={"file": ("story.html", PAGE.encode(), "text/html")})
    assert response.status_code == 413 and "150 MB" in response.json()["detail"]


def test_the_file_route_body_cap_follows_the_file_limit() -> None:
    from spyglass_service.radar import import_files

    assert importer_api.FILE_FORM_BYTES == import_files.MAX_FILE_BYTES + 256 * 1024
    assert import_files.MAX_FILE_MB == 150


def test_files_are_refused_from_another_site(env) -> None:
    response = env.client.post("/api/radar/import/file", headers=CROSS_SITE, data={"url": URL},
                               files={"file": ("story.html", PAGE.encode(), "text/html")})
    assert response.status_code == 403


def test_a_page_over_six_megabytes_is_refused_by_either_transport(env, monkeypatch) -> None:
    monkeypatch.setattr(import_staging, "MAX_HTML_BYTES", 1_000)
    assert stage_json(env).status_code == 413
    assert stage_form(env).headers["location"] == "/#/import?error=size"


def test_an_empty_form_page_lands_on_a_fixed_error(env) -> None:
    response = stage_form(env, html="   ")
    assert response.headers["location"] == "/#/import?error=empty"


def test_a_form_that_carries_a_file_part_is_refused(env) -> None:
    files = {"url": (None, URL), "key": (None, env.key), "html": ("page.html", PAGE.encode(), "text/html")}
    response = env.client.post(STAGE, files=files, headers=CROSS_SITE)
    assert response.headers["location"] == "/#/import?error=form"
