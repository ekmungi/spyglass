"""The reading browser launches the installed Edge when a channel is configured.

A fake `patchright.sync_api` module stands in for the real one, so no browser starts.
"""

import contextlib
import sys
import types

from spyglass_service import fetch_rungs
from spyglass_service.config import Settings


class _FakePage:
    """A page that is already public and clear of any automated check."""

    url = "https://example.com/"

    def goto(self, url, timeout=None):
        """Pretend to navigate."""

    def content(self):
        """Rendered HTML of the fake page."""
        return "<html><body>rendered</body></html>"


class _FakeBrowser:
    """A browser that records that it was closed."""

    def close(self):
        """Nothing to tear down."""


def _install_fake_patchright(monkeypatch) -> dict:
    """Install a fake patchright whose `launch` records its keyword arguments."""
    seen: dict = {}

    class _Chromium:
        def launch(self, **kwargs):
            seen.update(kwargs)
            return _FakeBrowser()

    class _Playwright:
        chromium = _Chromium()

    @contextlib.contextmanager
    def sync_playwright():
        yield _Playwright()

    module = types.ModuleType("patchright.sync_api")
    module.sync_playwright = sync_playwright
    package = types.ModuleType("patchright")
    package.sync_api = module
    monkeypatch.setitem(sys.modules, "patchright", package)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", module)
    # The guarded page, the bot-check wait and the address check are tested elsewhere.
    monkeypatch.setattr(fetch_rungs, "open_guarded_page", lambda *a, **k: _FakePage())
    monkeypatch.setattr(fetch_rungs, "finish_render", lambda page, wait: page.content())
    monkeypatch.setattr(fetch_rungs, "chromium_args", lambda url: ["--guard"])
    return seen


def test_browser_rung_launches_edge_when_the_channel_is_set(monkeypatch):
    seen = _install_fake_patchright(monkeypatch)
    result = fetch_rungs.make_browser_rung(channel="msedge")("https://example.com/")
    assert result.ok
    assert seen["channel"] == "msedge"
    assert seen["args"] == ["--guard"]


def test_browser_rung_keeps_its_own_chromium_by_default(monkeypatch):
    seen = _install_fake_patchright(monkeypatch)
    result = fetch_rungs.make_browser_rung()("https://example.com/")
    assert result.ok
    assert seen["channel"] is None


def test_setting_defaults_to_empty_and_reads_the_environment(monkeypatch):
    monkeypatch.delenv("SPYGLASS_BROWSER_CHANNEL", raising=False)
    assert Settings().browser_channel == ""
    monkeypatch.setenv("SPYGLASS_BROWSER_CHANNEL", "msedge")
    assert Settings().browser_channel == "msedge"


def test_build_rungs_passes_the_setting_through(monkeypatch):
    monkeypatch.setenv("SPYGLASS_BROWSER_CHANNEL", "msedge")
    given: dict = {}

    def fake_make(**kwargs):
        given.update(kwargs)
        return lambda url: None

    monkeypatch.setattr(fetch_rungs, "make_browser_rung", fake_make)
    fetch_rungs.build_rungs(Settings(browser_enabled=True, jina_enabled=False))
    assert given["channel"] == "msedge"
