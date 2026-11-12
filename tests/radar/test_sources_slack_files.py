"""Files and pictures posted in the Slack capture channel arrive under "From you".

Everything runs against fake Slack answers: a fake Web API function, a fake downloader, and for the
download itself an httpx mock transport that records every request. No Slack credentials exist for
these tests and nothing touches the network.
"""

import httpx
import pymupdf
import pytest
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.models import Item
from spyglass_service.radar import from_you_store, media_proxy
from spyglass_service.radar.egress import SecretDestinationError, assert_secret_destination
from spyglass_service.radar.models import ItemState, ReaderDoc
from spyglass_service.radar.sources import slack_files
from spyglass_service.radar.sources.slack import collect_slack

from .test_sources_support import make_engine, make_settings

TOKEN = "xoxb-test-token"
PERMALINK = "https://team.slack.com/files/U1/F100/report.pdf"
DOWNLOAD = "https://files.slack.com/files-pri/T1-F100/download/report.pdf"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc`\x00\x02\x00\x00\x05\x00\x01")


def make_pdf(text: str = "Quarterly device review") -> bytes:
    """A real one-page PDF containing `text`."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def file_info(**over) -> dict:
    """A Slack file object as the Web API and the message events describe it."""
    base = {"id": "F100", "name": "report.pdf", "title": "report.pdf", "mimetype": "application/pdf",
            "filetype": "pdf", "size": 2048, "mode": "hosted", "url_private_download": DOWNLOAD,
            "permalink": PERMALINK}
    return {**base, **over}


def message(*files: dict, text: str = "worth reading", ts: str = "1700000000.000100") -> dict:
    """A message in the capture channel that carries files."""
    return {"type": "message", "ts": ts, "user": "U1", "text": text, "subtype": "file_share",
            "files": list(files)}


@pytest.fixture
def world(tmp_path):
    """An engine, settings with a data folder, and a downloader that serves `bodies` by URL."""
    engine = make_engine(tmp_path)
    settings = make_settings(data_dir=tmp_path, slack_bot_token=TOKEN, slack_capture_channel="C123")
    calls: list[str] = []
    bodies: dict[str, bytes] = {}

    def download(url: str) -> bytes:
        calls.append(url)
        if url not in bodies:
            raise slack_files.SlackFileRefused("Slack has no such file.")
        return bodies[url]

    yield SimpleWorld(engine, settings, bodies, calls, download, tmp_path)
    engine.dispose()


class SimpleWorld:
    """The pieces a test works with."""

    def __init__(self, engine, settings, bodies, calls, download, path) -> None:
        self.engine, self.settings, self.bodies = engine, settings, bodies
        self.calls, self.download, self.path = calls, download, path

    def run(self, msg: dict, note: str | None = "worth reading", api=None) -> list[int]:
        """Import the files of one message."""
        return slack_files.import_message_files(
            self.engine, self.settings, msg, note=note, token=TOKEN, download=self.download,
            api=api or (lambda _u, _p: {"ok": False, "error": "unused"}))

    def item(self, item_id: int):
        """(item, state, reader document) of an imported item."""
        with Session(self.engine) as session:
            return (session.get(Item, item_id),
                    session.exec(select(ItemState).where(ItemState.item_id == item_id)).one(),
                    session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first())


# ---- what is accepted --------------------------------------------------------------------------


@pytest.mark.parametrize("name,mimetype,filetype,expected", [
    ("a.pdf", "application/pdf", "pdf", "pdf"), ("A.PNG", "image/png", "png", "png"),
    ("p.jpg", "image/jpeg", "jpg", "jpeg"), ("p.jpeg", "", "", "jpeg"),
    ("p.webp", "image/webp", "webp", "webp"), ("n.txt", "text/plain", "text", "text"),
    ("n.md", "text/markdown", "markdown", "text"), ("n", "text/plain", "text", "text"),
    ("shot", "image/png", "png", "png"),
    ("a.zip", "application/zip", "zip", None), ("a.svg", "image/svg+xml", "svg", None),
    ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx", None),
    ("a.exe", "application/octet-stream", "exe", None), ("a.html", "text/html", "html", None),
])
def test_only_the_named_types_are_accepted(name, mimetype, filetype, expected) -> None:
    """PDF, PNG, JPEG, WebP, plain text and Markdown; everything else (SVG and HTML included) no."""
    assert slack_files.file_kind(name, mimetype, filetype) == expected


# ---- importing ---------------------------------------------------------------------------------


def test_a_pdf_becomes_a_readable_document_sent_in_via_slack(world) -> None:
    """The item is from you, via Slack, with the message as note, a stored PDF and its text."""
    world.bodies[DOWNLOAD] = make_pdf()
    [item_id] = world.run(message(file_info()))
    item, state, doc = world.item(item_id)
    assert item.title == "report.pdf" and item.url == PERMALINK
    assert state.from_user and state.captured_via == "slack" and state.user_note == "worth reading"
    assert doc.kind == "pdf"
    assert from_you_store.find(world.path, item_id)[0].read_bytes().startswith(b"%PDF")
    assert not (world.path / "pdf_cache").exists()
    assert "Quarterly device review" in content_store.get_fulltext(world.engine, item_id)["markdown"]


def test_a_picture_becomes_an_item_that_shows_the_picture(world) -> None:
    """The document holds the picture; the bytes sit in the image store and are served from it."""
    link = "https://team.slack.com/files/U1/F200/chart.png"
    world.bodies["https://files.slack.com/files-pri/T1-F200/download/chart.png"] = PNG
    info = file_info(id="F200", name="chart.png", title="chart", mimetype="image/png",
                     filetype="png", permalink=link,
                     url_private_download="https://files.slack.com/files-pri/T1-F200/download/chart.png")
    [item_id] = world.run(message(info, text="the funding chart"), note="the funding chart")
    item, state, doc = world.item(item_id)
    assert state.from_user and state.captured_via == "slack"
    assert state.user_note == "the funding chart"
    assert doc.kind == "article" and f'src="{link}"' in doc.html and "<img" in doc.html
    assert doc.lead_image == link
    got = media_proxy.serve(world.engine, world.path, link)
    assert got == (PNG, "image/png")
    assert from_you_store.find(world.path, item_id)[1] == "image/png"
    assert media_proxy.cache_get(world.path / "img_cache", link) is None  # not in the trimmed cache


def test_text_and_markdown_files_are_read_as_text(world) -> None:
    """A Markdown file's words are the document, and its name is the title."""
    url = "https://files.slack.com/files-pri/T1-F300/download/notes.md"
    world.bodies[url] = "# Notes\n\nThe regulator moved first.\n".encode()
    info = file_info(id="F300", name="notes.md", title="notes.md", mimetype="text/plain",
                     filetype="markdown", url_private_download=url,
                     permalink="https://team.slack.com/files/U1/F300/notes.md")
    [item_id] = world.run(message(info))
    item, _state, doc = world.item(item_id)
    assert item.title == "notes.md" and "The regulator moved first." in doc.html


def test_every_file_of_a_message_becomes_its_own_item_with_the_same_note(world) -> None:
    """Two files, two items, one note each."""
    world.bodies[DOWNLOAD] = make_pdf()
    second = "https://files.slack.com/files-pri/T1-F101/download/two.pdf"
    world.bodies[second] = make_pdf("Second report")
    info2 = file_info(id="F101", name="two.pdf", title="two.pdf", url_private_download=second,
                      permalink="https://team.slack.com/files/U1/F101/two.pdf")
    ids = world.run(message(file_info(), info2))
    assert len(ids) == 2 and len(set(ids)) == 2
    assert {world.item(i)[1].user_note for i in ids} == {"worth reading"}


def test_the_same_file_twice_is_one_item(world) -> None:
    """Handling a message again (a retry) does not duplicate its items."""
    world.bodies[DOWNLOAD] = make_pdf()
    first = world.run(message(file_info()))
    again = world.run(message(file_info()))
    assert first == again
    with Session(world.engine) as session:
        assert len(session.exec(select(Item)).all()) == 1


# ---- what is refused ---------------------------------------------------------------------------


def test_a_file_over_twenty_megabytes_becomes_an_item_with_the_reason(world) -> None:
    """It is not downloaded; the item carries the file name and a plain sentence."""
    [item_id] = world.run(message(file_info(size=21 * 1024 * 1024)))
    item, state, doc = world.item(item_id)
    assert world.calls == []
    assert item.title == "report.pdf" and state.user_note == "worth reading"
    assert "not imported" in doc.html and "20 MB" in doc.html


def test_another_type_becomes_an_item_with_the_reason(world) -> None:
    """A zip file is named and explained, not downloaded."""
    info = file_info(name="data.zip", title="data.zip", mimetype="application/zip", filetype="zip")
    [item_id] = world.run(message(info))
    item, _state, doc = world.item(item_id)
    assert world.calls == [] and item.title == "data.zip"
    assert "PDF, PNG, JPEG, WebP, plain text and Markdown" in doc.html


def test_a_file_that_is_not_what_its_name_says_is_refused(world) -> None:
    """A page of HTML named .png is not stored as a picture."""
    world.bodies[DOWNLOAD] = b"<html><body>hello</body></html>"
    info = file_info(name="trick.png", title="trick.png", mimetype="image/png", filetype="png")
    [item_id] = world.run(message(info))
    _item, _state, doc = world.item(item_id)
    assert "not imported" in doc.html and "does not look like" in doc.html
    assert media_proxy.cache_get(world.path / "img_cache", PERMALINK) is None


def test_a_download_slack_refuses_is_an_item_with_the_reason(world) -> None:
    """When Slack will not hand the file over, the item says so and keeps the message note."""
    [item_id] = world.run(message(file_info()))  # no body registered: the downloader refuses
    item, state, doc = world.item(item_id)
    assert item.title == "report.pdf" and state.user_note == "worth reading"
    assert "not imported" in doc.html and "Slack has no such file." in doc.html


def test_a_passing_download_failure_is_retried_not_recorded(world) -> None:
    """A timeout leaves no item and raises, so the message is read again next time."""
    def flaky(_url: str) -> bytes:
        raise slack_files.SlackFileTransient("Slack did not answer in time.")

    with pytest.raises(slack_files.SlackFileTransient):
        slack_files.import_message_files(world.engine, world.settings, message(file_info()),
                                         note=None, token=TOKEN, download=flaky,
                                         api=lambda _u, _p: {})
    with Session(world.engine) as session:
        assert session.exec(select(Item)).all() == []


def test_without_a_bot_token_the_files_are_named_and_explained(world) -> None:
    """The live connection alone cannot download; the item says what is missing."""
    [item_id] = slack_files.import_message_files(
        world.engine, world.settings, message(file_info()), note="n", token=None,
        download=None, api=None)
    _item, _state, doc = world.item(item_id)
    assert "bot token" in doc.html and "files:read" in doc.html


def test_a_file_outside_slack_is_named_and_explained(world) -> None:
    """A file kept in another service (no download address) cannot be read."""
    info = file_info(mode="external", url_private_download="", url_private="")
    [item_id] = world.run(message(info))
    _item, _state, doc = world.item(item_id)
    assert "outside Slack" in doc.html


def test_minimal_file_entries_are_looked_up_first(world) -> None:
    """A shared file that arrives as a stub is completed with files.info before it is judged."""
    world.bodies[DOWNLOAD] = make_pdf()
    asked: list[dict] = []

    def api(url: str, params: dict) -> dict:
        asked.append({"url": url, **params})
        return {"ok": True, "file": file_info()}

    stub = {"id": "F100", "file_access": "check_file_info"}
    [item_id] = world.run(message(stub), api=api)
    assert asked == [{"url": "https://slack.com/api/files.info", "file": "F100"}]
    assert world.item(item_id)[2].kind == "pdf"


def test_deleted_files_and_bare_ids_are_not_recorded(world) -> None:
    """Slack's placeholders for deleted or unreachable files describe nothing, so make no item."""
    stubs = [{"id": "F1"}, {"id": "F2", "mode": "tombstone"},
             {"id": "F3", "file_access": "file_not_found"}]
    assert world.run(message(*stubs)) == []
    with Session(world.engine) as session:
        assert session.exec(select(Item)).all() == []


def test_a_file_with_no_address_at_all_is_skipped(world) -> None:
    """With no permalink and no id there is nothing to record; the message's other files still work."""
    world.bodies[DOWNLOAD] = make_pdf()
    ids = world.run(message({"name": "x.pdf"}, file_info()))
    assert len(ids) == 1


# ---- the two routes ----------------------------------------------------------------------------


def test_the_timer_route_imports_files_and_links_of_one_message(world, monkeypatch) -> None:
    """collect_slack counts both, advances the watermark, and records the file under From you."""
    from spyglass_service.radar import capture

    monkeypatch.setattr(capture, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(capture, "_default_title", lambda url: "Title")
    world.bodies[DOWNLOAD] = make_pdf()
    msg = {**message(file_info(), text="<https://example.org/a|a page> and a file"), "ts": "1700000001.0"}
    pages = [{"ok": True, "messages": [msg], "has_more": False}]
    captured = collect_slack(world.engine, world.settings, transport=lambda _u, _p: pages.pop(0),
                             download=world.download)
    assert captured == 2
    with Session(world.engine) as session:
        assert {i.url for i in session.exec(select(Item)).all()} == {PERMALINK, "https://example.org/a"}


def test_the_timer_route_holds_the_message_after_a_passing_failure(world) -> None:
    """If a download times out the watermark stays before the message, so it is retried."""
    from spyglass_service.radar.models import RadarDoc

    def flaky(_url: str) -> bytes:
        raise slack_files.SlackFileTransient("timeout")

    msg = {**message(file_info(), text="a file"), "ts": "1700000002.0"}
    pages = [{"ok": True, "messages": [msg], "has_more": False}]
    collect_slack(world.engine, world.settings, transport=lambda _u, _p: pages.pop(0), download=flaky)
    with Session(world.engine) as session:
        assert session.get(RadarDoc, "slack_watermark") is None
        assert session.exec(select(Item)).all() == []


def test_the_live_route_imports_files_and_announces_the_items(world) -> None:
    """A message event with a file is handled like the timer route's, and the item is announced."""
    from spyglass_service.radar.sources.slack_live import SlackLiveListener

    world.bodies[DOWNLOAD] = make_pdf()
    announced: list[int] = []
    settings = make_settings(data_dir=world.path, slack_app_token="xapp-test",
                             slack_bot_token=TOKEN, slack_capture_channel="C123")
    listener = SlackLiveListener(world.engine, settings, on_capture=announced.append,
                                 download=world.download)
    event = {**message(file_info()), "channel": "C123", "ts": "1700000003.0"}
    listener._on_event(event)
    assert len(announced) == 1
    assert world.item(announced[0])[1].captured_via == "slack"


# ---- the download itself: hosts, redirects, size, sign-in pages --------------------------------


def downloader(handler, token: str = TOKEN):
    """The real downloader over a mock transport."""
    return slack_files.make_downloader(token, http_transport=httpx.MockTransport(handler))


def test_the_token_goes_only_to_the_slack_file_host() -> None:
    """The bot token is bound to slack.com and files.slack.com, exactly."""
    assert_secret_destination("slack_bot_token", "https://files.slack.com/files-pri/x")
    assert_secret_destination("slack_bot_token", "https://slack.com/api/files.info")
    for bad in ("https://evil.example/x", "https://files.slack.com.evil.example/x",
                "https://notfiles.slack.com/x", "http://files.slack.com/x",
                "https://user" "@files.slack.com/x", "https://team.slack.com/files/x"):
        with pytest.raises(SecretDestinationError):
            assert_secret_destination("slack_bot_token", bad)


def test_the_downloader_sends_the_token_to_the_file_host_and_returns_the_bytes() -> None:
    """One authorised GET to files.slack.com."""
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"%PDF-1.4 body", headers={"content-type": "application/pdf"})

    assert downloader(handler)(DOWNLOAD) == b"%PDF-1.4 body"
    assert len(seen) == 1 and seen[0].url.host == "files.slack.com"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("url", ["https://evil.example/f.pdf", "http://files.slack.com/f.pdf",
                                 "https://slack.com/api/auth.test",
                                 "https://team.slack.com/files/U1/F1/f.pdf", "file:///etc/passwd"])
def test_the_downloader_refuses_other_addresses_without_sending_anything(url) -> None:
    """Only https on the file host; no request, so no token, leaves for anything else."""
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"x")

    with pytest.raises(slack_files.SlackFileRefused):
        downloader(handler)(url)
    assert seen == []


def test_a_redirect_off_slack_is_not_followed_and_does_not_carry_the_token() -> None:
    """A redirect to another host is refused before it is requested."""
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    with pytest.raises(slack_files.SlackFileRefused):
        downloader(handler)(DOWNLOAD)
    assert [r.url.host for r in seen] == ["files.slack.com"]


def test_a_redirect_within_the_file_host_is_followed_with_the_token() -> None:
    """Slack may hop between paths of its file host; the token goes along, only there."""
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("download/report.pdf"):
            return httpx.Response(302, headers={"location": "/files-tmb/other"})
        return httpx.Response(200, content=b"%PDF-1.4 ok")

    assert downloader(handler)(DOWNLOAD) == b"%PDF-1.4 ok"
    assert all(r.url.host == "files.slack.com" and "authorization" in r.headers for r in seen)


def test_the_size_cap_applies_to_the_declared_and_the_actual_size() -> None:
    """Over 20 MB is refused from the header, or while streaming when the header is missing."""
    limit = slack_files.MAX_FILE_BYTES
    declared = lambda r: httpx.Response(200, headers={"content-length": str(limit + 1)}, content=b"x")  # noqa: E731
    with pytest.raises(slack_files.SlackFileRefused, match="20 MB"):
        downloader(declared)(DOWNLOAD)

    def streamed(request):
        return httpx.Response(200, content=iter([b"x" * (limit // 2), b"x" * (limit // 2), b"xx"]))

    with pytest.raises(slack_files.SlackFileRefused, match="20 MB"):
        downloader(streamed)(DOWNLOAD)


def test_a_sign_in_page_instead_of_a_file_names_the_missing_permission() -> None:
    """Without files:read Slack answers with an HTML page; the reason says what to add."""
    page = lambda r: httpx.Response(200, content=b"<html>sign in</html>", headers={"content-type": "text/html"})  # noqa: E731
    with pytest.raises(slack_files.SlackFileRefused, match="files:read"):
        downloader(page)(DOWNLOAD)
    forbidden = lambda r: httpx.Response(403)  # noqa: E731
    with pytest.raises(slack_files.SlackFileRefused, match="files:read"):
        downloader(forbidden)(DOWNLOAD)


def test_server_errors_and_timeouts_are_passing_failures() -> None:
    """5xx, 429 and network errors are retried later, not recorded as refusals."""
    with pytest.raises(slack_files.SlackFileTransient):
        downloader(lambda r: httpx.Response(503))(DOWNLOAD)
    with pytest.raises(slack_files.SlackFileTransient):
        downloader(lambda r: httpx.Response(429))(DOWNLOAD)

    def broken(request):
        raise httpx.ConnectError("down")

    with pytest.raises(slack_files.SlackFileTransient):
        downloader(broken)(DOWNLOAD)


def test_a_missing_file_is_a_refusal_with_a_reason() -> None:
    """404 means the file was deleted in Slack."""
    with pytest.raises(slack_files.SlackFileRefused, match="no longer"):
        downloader(lambda r: httpx.Response(404))(DOWNLOAD)
