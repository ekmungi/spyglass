"""The browser's automated-check handling: read-only by default, a narrow switch to allow it."""

import types

import pytest

from spyglass_service import fetch_bot_check, fetch_rungs
from spyglass_service.config import Settings
from spyglass_service.fetch_bot_check import (
    BOT_CHECK_REASON,
    is_challenge_request,
    looks_like_bot_check,
    registrable_domain,
    wait_out_bot_check,
)


class _Route:
    """Records whether the guard aborted or continued a request."""

    def __init__(self) -> None:
        self.action: str | None = None

    def abort(self) -> None:
        """Mark aborted."""
        self.action = "abort"

    def continue_(self) -> None:
        """Mark continued."""
        self.action = "continue"


def _frame(url: str, *, main: bool = False) -> types.SimpleNamespace:
    """A fake browser frame: the main frame has no parent, a sub-frame has one."""
    return types.SimpleNamespace(url=url, parent_frame=None if main else object())


MAIN_FRAME = _frame("https://news.example.com/story", main=True)


def _decide(guard, url: str, method: str = "POST", *, frame=MAIN_FRAME, nav: bool = False) -> str | None:
    """What `guard` does with one request made from `frame` (the main page by default)."""
    route = _Route()
    guard(route, types.SimpleNamespace(url=url, method=method, frame=frame,
                                       is_navigation_request=lambda: nav))
    return route.action


CHALLENGE = "https://news.example.com/cdn-cgi/challenge-platform/h/b/flow/ov1/abc"
TURNSTILE = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/ov2"


@pytest.mark.parametrize("url", [CHALLENGE, TURNSTILE])
def test_with_the_switch_off_every_write_is_aborted(url: str) -> None:
    """Read-only by default: even the checking service's own endpoints get no POST."""
    guard = fetch_rungs.make_request_guard(page_url="https://news.example.com/story")
    assert _decide(guard, url) == "abort"


@pytest.mark.parametrize("url", [CHALLENGE, TURNSTILE,
                                 "https://www.example.com/cdn-cgi/challenge-platform/x"])
def test_with_the_switch_on_only_challenge_endpoints_may_receive_a_write(url: str) -> None:
    """The checking service's endpoints on the page's own domain, or its challenge host, pass."""
    guard = fetch_rungs.make_request_guard(allow_bot_checks=True,
                                           page_url="https://news.example.com/story")
    assert _decide(guard, url) == "continue"


@pytest.mark.parametrize("url", [
    "https://news.example.com/comments/post",  # same site, not a challenge path
    "https://tracker.example.net/cdn-cgi/challenge-platform/h/b",  # another site's path
    "https://evil.example/collect",
    "http://10.0.0.5/cdn-cgi/challenge-platform/h/b",  # private address, even on the path
])
def test_with_the_switch_on_every_other_write_is_still_aborted(url: str) -> None:
    """Nothing but the challenge endpoints may receive a write."""
    guard = fetch_rungs.make_request_guard(allow_bot_checks=True,
                                           page_url="https://news.example.com/story")
    assert _decide(guard, url) == "abort"


def test_reads_stay_allowed_with_either_setting() -> None:
    """GET of a public page continues whatever the switch says."""
    for allow in (False, True):
        guard = fetch_rungs.make_request_guard(allow_bot_checks=allow,
                                               page_url="https://news.example.com/")
        assert _decide(guard, "https://cdn.example.org/a.js", "GET") == "continue"


def test_registrable_domain_handles_common_two_part_suffixes() -> None:
    """www and other subdomains collapse to the domain; co.uk-style suffixes keep three parts."""
    assert registrable_domain("www.news.example.com") == "example.com"
    assert registrable_domain("www.bbc.co.uk") == "bbc.co.uk"
    assert registrable_domain("example.com") == "example.com"
    assert registrable_domain("") == ""


def test_is_challenge_request_needs_the_path_and_the_domain() -> None:
    """A challenge endpoint is the path on one of the page's domains, or the challenge host."""
    assert is_challenge_request(CHALLENGE, {"example.com"})
    assert is_challenge_request(TURNSTILE, set())
    assert not is_challenge_request("https://example.com/cdn-cgi/other", {"example.com"})
    assert not is_challenge_request(CHALLENGE, {"other.org"})


@pytest.mark.parametrize("title,body", [
    ("Just a moment...", "<html></html>"),
    ("news.example.com", "<p>Verification successful. Waiting for news.example.com to respond</p>"),
    ("", "<h1>Performing security verification</h1>"),
])
def test_known_interstitials_are_recognised(title: str, body: str) -> None:
    """The phrases of common automated-check pages are recognised."""
    assert looks_like_bot_check(title, body)


def test_an_ordinary_article_is_not_an_interstitial() -> None:
    """A real page with ordinary text passes."""
    assert not looks_like_bot_check("FDA clears polyp AI", "<article>The agency said...</article>")


class _Page:
    """A page that shows an interstitial for `clears_after` seconds of waiting, on a fake clock."""

    def __init__(self, clock: list[float], clears_after: float | None) -> None:
        self.clock, self.clears_after, self.waited = clock, clears_after, 0.0

    def title(self) -> str:
        """The interstitial's title until it clears."""
        cleared = self.clears_after is not None and self.waited >= self.clears_after
        return "The real article" if cleared else "Just a moment..."

    def content(self) -> str:
        """Body to match the title."""
        return "<article>text</article>" if self.title() == "The real article" else "<p>checking</p>"

    def wait_for_timeout(self, ms: float) -> None:
        """Advance the fake clock."""
        self.waited += ms / 1000
        self.clock[0] += ms / 1000


def test_waiting_returns_once_the_interstitial_clears() -> None:
    """A check that clears on its own is waited out."""
    clock = [0.0]
    page = _Page(clock, clears_after=3.0)
    assert wait_out_bot_check(page, 8.0, clock=lambda: clock[0]) is True
    assert 3.0 <= clock[0] < 8.0


def test_waiting_gives_up_at_the_limit() -> None:
    """A check that never clears is abandoned at the time limit."""
    clock = [0.0]
    assert wait_out_bot_check(_Page(clock, clears_after=None), 8.0, clock=lambda: clock[0]) is False
    assert 8.0 <= clock[0] < 9.0


def test_the_wait_is_8_seconds_off_and_20_seconds_on() -> None:
    """The switch also sets how long the browser waits for a check to clear."""
    assert fetch_bot_check.wait_seconds(False) == 8.0
    assert fetch_bot_check.wait_seconds(True) == 20.0


def test_the_browser_rung_reports_an_uncleared_check_with_the_plain_reason(monkeypatch) -> None:
    """A page that stays on the interstitial fails with the agreed reason."""
    clock = [0.0]
    monkeypatch.setattr(fetch_bot_check, "_clock", lambda: clock[0])
    result = fetch_rungs.make_browser_rung(
        renderer=lambda url: fetch_rungs.finish_render(_Page(clock, None), 8.0))(
        "https://news.example.com/story")
    assert result.ok is False and result.error == BOT_CHECK_REASON


def test_build_rungs_passes_the_switch_to_the_browser(monkeypatch, tmp_path) -> None:
    """The ladder's browser rung follows `privacy_allow_bot_checks`."""
    seen: list[bool] = []
    monkeypatch.setattr(fetch_rungs, "make_browser_rung",
                        lambda **kw: seen.append(kw.get("allow_bot_checks")) or (lambda u: None))
    for allow in (False, True):
        fetch_rungs.build_rungs(Settings(_env_file=None, data_dir=tmp_path, browser_enabled=True,
                                         privacy_allow_bot_checks=allow), "html")
    assert seen == [False, True]


def _guard():
    """A guard with the switch on for a page on news.example.com."""
    return fetch_rungs.make_request_guard(allow_bot_checks=True, page_url="https://news.example.com/story")


FOREIGN_CHALLENGE = "https://tracker.example.net/cdn-cgi/challenge-platform/h/b"


def test_a_sub_frame_navigation_does_not_widen_the_allowance() -> None:
    """A page can embed a frame from another domain; that must not allow the domain's challenge path."""
    guard = _guard()
    iframe = _frame("https://tracker.example.net/embed")
    assert _decide(guard, "https://tracker.example.net/embed", "GET", frame=iframe, nav=True) == "continue"
    assert _decide(guard, FOREIGN_CHALLENGE) == "abort"


def test_a_main_frame_navigation_widens_the_allowance() -> None:
    """A redirect of the page itself to another domain makes that domain the page's own."""
    guard = _guard()
    main = _frame("https://other.example.net/", main=True)
    assert _decide(guard, "https://other.example.net/", "GET", frame=main, nav=True) == "continue"
    assert _decide(guard, FOREIGN_CHALLENGE, frame=main) == "continue"


def test_a_navigation_with_no_known_frame_does_not_widen() -> None:
    """A navigation request whose frame cannot be read is treated as a sub-frame."""
    guard = _guard()

    class _NoFrame:
        url = "https://tracker.example.net/embed"
        method = "GET"

        @property
        def frame(self):
            raise RuntimeError("frame not available")

        def is_navigation_request(self) -> bool:
            return True

    guard(_Route(), _NoFrame())
    assert _decide(guard, FOREIGN_CHALLENGE) == "abort"


def test_a_challenge_post_from_a_foreign_frame_is_refused() -> None:
    """The write is allowed only from the page's own domain or from the checking service's host."""
    guard = _guard()
    foreign = _frame("https://evil.example.org/frame")
    assert _decide(guard, CHALLENGE, frame=foreign) == "abort"
    assert _decide(guard, TURNSTILE, frame=foreign) == "abort"
    assert _decide(guard, CHALLENGE, frame=_frame("about:blank")) == "abort"
    own = _frame("https://www.example.com/widget")
    assert _decide(guard, CHALLENGE, frame=own) == "continue"
    service = _frame("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/ov2")
    assert _decide(guard, TURNSTILE, frame=service) == "continue"


def test_a_write_with_no_readable_frame_is_refused() -> None:
    """Fail closed: when the request's frame cannot be read, the write is not sent."""
    guard = _guard()
    route = _Route()
    guard(route, types.SimpleNamespace(url=CHALLENGE, method="POST"))
    assert route.action == "abort"


@pytest.mark.parametrize("host,expected", [
    ("www.bbc.co.uk", "bbc.co.uk"), ("a.b.abc.com.au", "abc.com.au"), ("news.yahoo.co.jp", "yahoo.co.jp"),
    ("www.globo.com.br", "globo.com.br"), ("x.service.gov.uk", "service.gov.uk"),
    ("alice.github.io", "alice.github.io"), ("bob.github.io", "bob.github.io"),
    ("www.example.com", "example.com"),
])
def test_registrable_domain_knows_common_suffixes_and_shared_hosts(host: str, expected: str) -> None:
    """Two-level country suffixes and shared hosting domains keep one more label."""
    assert registrable_domain(host) == expected
