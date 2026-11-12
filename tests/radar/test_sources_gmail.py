"""Tests for email parsing and the Gmail collector (fixture messages, fake IMAP client).

These do not exercise a real Gmail account.
"""

import pytest
from sqlmodel import Session, select

from spyglass_service.content_store import get_fulltext
from spyglass_service.models import Item
from spyglass_service.radar.models import ItemState, RadarDoc, ReaderDoc, loads
from spyglass_service.radar.sources._common import NotConfigured
from spyglass_service.radar.sources.email_parse import (
    find_browser_link,
    first_url,
    html_to_text,
    item_url,
    parse_message,
)
from spyglass_service.radar.sources.gmail import collect_gmail, gmail_configured

from .test_sources_support import all_items, make_email, make_engine, make_settings

NEWSLETTER_HTML = (
    '<html><body><p>Hi</p><a href="https://web.example/p/1?x=1">View in browser</a>'
    "<h2>Big news</h2><p>Body text here.</p><script>alert(1)</script>"
    '<img src="https://t.example/p.gif" width="1" height="1"></body></html>'
)


class FakeImap:
    """Just enough of imaplib.IMAP4_SSL: labels map to {uid: raw message bytes}."""

    def __init__(self, labels: dict[str, dict[int, bytes]], validity: str = "7") -> None:
        self.labels, self.validity = labels, validity
        self.current: dict[int, bytes] = {}
        self.readonly_seen: list[bool] = []
        self.logged_out = False

    def select(self, mailbox: str, readonly: bool = False):
        self.readonly_seen.append(readonly)
        name = mailbox.strip('"')
        if name not in self.labels:
            return "NO", [b"nope"]
        self.current = self.labels[name]
        return "OK", [str(len(self.current)).encode()]

    def response(self, code: str):
        return code, [self.validity.encode()]

    def uid(self, command: str, *args):
        if command == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(self.current)).encode()]
        uid = int(args[0])
        return "OK", [(b"%d (UID %d BODY[] {1}" % (uid, uid), self.current[uid]), b")"]

    def logout(self):
        self.logged_out = True


def raw(msg) -> bytes:
    return msg.as_bytes()


def configured(**kw):
    return make_settings(gmail_address="me@example.com", gmail_app_password="pw", **kw)


def test_parse_message_extracts_sender_subject_links_and_text() -> None:
    parsed = parse_message(make_email(html=NEWSLETTER_HTML, text="plain version"), "fb")
    assert parsed.sender == "The Digest" and parsed.subject == "Weekly digest"
    assert parsed.message_id == "abc123@example.com"
    assert parsed.browser_url == "https://web.example/p/1?x=1"
    assert parsed.text == "plain version" and parsed.date.year == 2026
    assert item_url(parsed) == "https://web.example/p/1?x=1"


def test_parse_message_falls_back_to_html_text_and_gmail_search_url() -> None:
    parsed = parse_message(make_email(html="<p>Only <b>html</b></p>", message_id=None), "lbl:9")
    assert parsed.text == "Only\nhtml" or parsed.text.replace("\n", " ") == "Only html"
    assert parsed.message_id == "lbl:9" and parsed.browser_url is None
    assert item_url(parsed) == "https://mail.google.com/mail/u/0/#search/rfc822msgid:lbl%3A9"


def test_find_browser_link_matches_common_phrases_only() -> None:
    for label in ("View in browser", "Read online", "view this email in your browser",
                  "View as a Web Page"):
        assert find_browser_link(f'<a href="https://x.example/a">{label}</a>')
    assert find_browser_link('<a href="https://x.example/a">Unsubscribe</a>') is None
    assert find_browser_link('<a href="/relative">View in browser</a>') is None
    assert find_browser_link("") is None


def test_first_url_and_html_to_text_helpers() -> None:
    assert first_url("see https://a.example/x?y=1, then more") == "https://a.example/x?y=1"
    assert first_url("nothing here") is None
    assert "alert" not in html_to_text("<style>x{}</style><p>hi</p><script>alert(1)</script>")


def test_collect_gmail_not_configured_raises() -> None:
    assert not gmail_configured(make_settings())
    with pytest.raises(NotConfigured):
        collect_gmail(None, make_settings())


def test_newsletters_become_items_with_reader_doc_and_text(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        imap = FakeImap({"Newsletters": {5: raw(make_email(html=NEWSLETTER_HTML))}})
        result = collect_gmail(engine, configured(), connect=lambda s: imap, captures=False)
        assert result == {"newsletter": 1, "capture": 0}
        (item,) = all_items(engine, "newsletter")
        assert (item.origin, item.title) == ("The Digest", "Weekly digest")
        assert item.url == "https://web.example/p/1?x=1"
        with Session(engine) as session:
            doc = session.exec(select(ReaderDoc)).one()
            assert doc.kind == "email" and "Big news" in doc.html
            assert "<script" not in doc.html and "alert" not in doc.html
            assert 't.example/p.gif' not in doc.html  # tracking pixel dropped
        assert "Body text here" in get_fulltext(engine, item.id)["markdown"]
        assert imap.readonly_seen == [True] and imap.logged_out
    finally:
        engine.dispose()


def test_seen_uids_are_remembered_and_validity_change_resets_them(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        messages = {5: raw(make_email(html=NEWSLETTER_HTML))}
        collect_gmail(engine, configured(), connect=lambda s: FakeImap({"Newsletters": messages}),
                      captures=False)
        again = collect_gmail(engine, configured(),
                              connect=lambda s: FakeImap({"Newsletters": messages}),
                              captures=False)
        assert again["newsletter"] == 0
        with Session(engine) as session:
            seen = loads(session.get(RadarDoc, "gmail_seen").body)
        assert seen["Newsletters"] == {"validity": "7", "uids": [5]}
        # A new UIDVALIDITY means UIDs were reassigned: the list is reset (dedupe by id holds).
        collect_gmail(engine, configured(),
                      connect=lambda s: FakeImap({"Newsletters": messages}, validity="8"),
                      captures=False)
        with Session(engine) as session:
            assert loads(session.get(RadarDoc, "gmail_seen").body)["Newsletters"]["validity"] == "8"
        assert len(all_items(engine, "newsletter")) == 1
    finally:
        engine.dispose()


def test_capture_label_messages_are_captured_with_the_readers_words(tmp_path, monkeypatch) -> None:
    engine = make_engine(tmp_path)
    try:
        from spyglass_service.radar import capture as capture_mod

        monkeypatch.setattr(capture_mod, "_resolve", lambda host: ["93.184.216.34"])
        monkeypatch.setattr(capture_mod, "_default_title", lambda url: "Fetched Title")
        mail = make_email(sender="Me <me@example.com>", subject="Fwd", text="worth a look https://example.org/cool-post thanks")
        none = make_email(sender="Me <me@example.com>", subject="No link", text="just words", message_id="<n@x>")
        imap = FakeImap({"Spyglass": {1: raw(mail), 2: raw(none)}})
        result = collect_gmail(engine, configured(), connect=lambda s: imap, newsletters=False)
        assert result["capture"] == 1
        (item,) = all_items(engine, "capture")
        assert item.url == "https://example.org/cool-post" and item.title == "Fetched Title"
        with Session(engine) as session:
            state = session.exec(select(ItemState)).one()
            assert state.captured_via == "email" and state.user_note == "worth a look thanks"
            seen = loads(session.get(RadarDoc, "gmail_seen").body)["Spyglass"]["uids"]
        assert seen == [1, 2]  # the message without a link is not retried forever
    finally:
        engine.dispose()


def test_failed_capture_is_left_unseen_for_retry(tmp_path, monkeypatch) -> None:
    engine = make_engine(tmp_path)
    try:
        from spyglass_service.radar.sources import gmail as gmail_mod

        def boom(*a, **k):
            raise RuntimeError("db locked")

        monkeypatch.setattr(gmail_mod, "capture_url", boom)
        imap = FakeImap({"Spyglass": {3: raw(make_email(sender="Me <me@example.com>", text="https://example.org/x"))}})
        collect_gmail(engine, configured(), connect=lambda s: imap, newsletters=False)
        with Session(engine) as session:
            assert loads(session.get(RadarDoc, "gmail_seen").body)["Spyglass"]["uids"] == []
    finally:
        engine.dispose()


def test_missing_label_reports_an_error_when_every_label_fails(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        imap = FakeImap({})
        with pytest.raises(RuntimeError, match="not found"):
            collect_gmail(engine, configured(), connect=lambda s: imap)
        assert imap.logged_out
        # One label failing is tolerated when the other works.
        imap = FakeImap({"Newsletters": {1: raw(make_email(html=NEWSLETTER_HTML))}})
        assert collect_gmail(engine, configured(), connect=lambda s: imap)["newsletter"] == 1
        assert session_item_count(engine) == 1
    finally:
        engine.dispose()


def session_item_count(engine) -> int:
    with Session(engine) as session:
        return len(session.exec(select(Item)).all())


def test_capture_from_another_sender_is_ignored(tmp_path) -> None:
    """A stranger's message under the capture label is never treated as the reader's capture."""
    engine = make_engine(tmp_path)
    try:
        stranger = make_email(sender="Someone <someone@example.org>",
                              text="https://example.org/planted")
        imap = FakeImap({"Spyglass": {7: raw(stranger)}})
        result = collect_gmail(engine, configured(), connect=lambda s: imap, newsletters=False)
        assert result["capture"] == 0
        with Session(engine) as session:
            assert session.exec(select(ItemState)).all() == []
            # Marked as handled so it is not re-read on every run.
            assert loads(session.get(RadarDoc, "gmail_seen").body)["Spyglass"]["uids"] == [7]
    finally:
        engine.dispose()


def test_capture_with_failed_sender_check_is_ignored(tmp_path) -> None:
    """A message that claims the reader's address but failed DKIM is not a capture."""
    engine = make_engine(tmp_path)
    try:
        forged = make_email(sender="Me <me@example.com>", text="https://example.org/forged")
        forged["Authentication-Results"] = "mx.example.com; dkim=fail header.d=example.com"
        imap = FakeImap({"Spyglass": {8: raw(forged)}})
        result = collect_gmail(engine, configured(), connect=lambda s: imap, newsletters=False)
        assert result["capture"] == 0
    finally:
        engine.dispose()
