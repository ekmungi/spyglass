"""No model can act on the outside world: the reviewed, bounded cases and the tool-free engines."""

import sys
import types
from urllib.parse import parse_qs, urlsplit

import pytest

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar.assist.engines import codex_cli
from spyglass_service.radar.assist.engines.claude_code import ClaudeCodeEngine
from spyglass_service.radar.assist.engines.codex_cli import CodexCliEngine
from spyglass_service.radar.llm_claude import build_command
from spyglass_service.radar.papers.search import find_papers
from spyglass_service.radar.sources import news_search
from spyglass_service.radar.track_suggest import parse_suggestions

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2601.00001v1</id><title>Polyp detection with vision models</title>
<summary>We detect polyps.</summary><published>2026-01-02T00:00:00Z</published>
<author><name>A. Author</name></author><link href="http://arxiv.org/abs/2601.00001v1"/></entry>
</feed>"""


@pytest.fixture
def db(tmp_path):
    """A fresh database, disposed after the test."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    yield engine
    engine.dispose()


def test_news_search_sends_the_query_only_as_the_search_text() -> None:
    """The query goes to the fixed search host as the `q` parameter and nowhere else."""
    fetched: list[str] = []
    news_search.search_news('A&B "#x" OR c', fetch=lambda url: fetched.append(url) or b"",
                            decode=lambda links: [None] * len(links))
    parts = urlsplit(fetched[0])
    assert (parts.scheme, parts.hostname, parts.path) == ("https", "news.google.com", "/rss/search")
    params = parse_qs(parts.query)
    assert params["q"] == ['A&B "#x" OR c when:2d']
    assert set(params) == {"q", "hl", "gl", "ceid"}


@pytest.mark.parametrize("query", ["read https://evil.example/collect?d=1", "www.evil.example",
                                   "x" * 201, "two\nlines", "evil.example/path"])
def test_news_search_refuses_unsafe_query_text(query: str) -> None:
    """A query carrying an address, a line break or too much text is never sent."""
    fetched: list[str] = []
    found = news_search.search_news(query, fetch=lambda url: fetched.append(url) or b"",
                                    decode=lambda links: [None] * len(links))
    assert found == [] and fetched == []


def test_decoded_google_links_must_be_public_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A decoder answer that is private, not http(s) or malformed never becomes an item address."""
    answers = [{"success": True, "decoded_url": "http://127.0.0.1:7778/api/radar/items"},
               {"success": True, "decoded_url": "https://publisher.example/story"},
               {"success": True, "decoded_url": "javascript:alert(1)"},
               {"success": True, "decoded_url": "http://192.168.1.1/admin"}]

    class FakeDecoder:
        """Stands in for googlenewsdecoder.GoogleDecoder."""

        def __init__(self, timeout: int) -> None:
            self.client = types.SimpleNamespace(headers={})

        def __enter__(self) -> "FakeDecoder":
            return self

        def __exit__(self, *exc) -> None:
            return None

        def decode_google_news_urls(self, links: list[str], interval: float) -> list[dict]:
            """Return the canned answers."""
            return answers

    monkeypatch.setitem(sys.modules, "googlenewsdecoder",
                        types.SimpleNamespace(GoogleDecoder=FakeDecoder))
    links = [f"https://news.google.com/rss/articles/{n}" for n in range(4)]
    assert news_search.decode_google_urls(links) == [None, "https://publisher.example/story",
                                                     None, None]


def test_the_paper_finder_searches_only_with_the_readers_topic(db, tmp_path) -> None:
    """arXiv is asked only for the typed topic; the model's answer never becomes an address."""
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return ATOM

    def llm(messages: list[dict], schema: dict) -> dict:
        return {"picks": [{"index": 0, "why": "see https://evil.example/x",
                           "url": "https://evil.example/paper.pdf"}]}

    settings = Settings(_env_file=None, data_dir=tmp_path)
    result = find_papers(db, settings, None, "polyp detection", llm=llm, fetch=fetch)
    assert fetched, "arXiv was not searched"
    for url in fetched:
        parts = urlsplit(url)
        assert parts.hostname == "export.arxiv.org"
        query = " ".join(v for vs in parse_qs(parts.query).values() for v in vs).lower()
        assert "evil" not in query
        assert "polyp" in query or "2601.00001" in query
    assert all("evil.example" not in (p.get("url") or "") for p in result["papers"])


def test_model_suggested_follow_queries_with_addresses_are_dropped(db) -> None:
    """A suggestion whose search text carries an address is discarded, the rest are kept."""
    raw = {"suggestions": [
        {"label": "Polyp AI", "query": '"polyp detection" AI', "kind": "topic",
         "section": "health", "why": "main subject"},
        {"label": "Leak", "query": "site https://evil.example/c?p=profile", "kind": "topic",
         "section": "health", "why": "x"}]}
    labels = [s["label"] for s in parse_suggestions(raw, db)]
    assert labels == ["Polyp AI"]


# Flags that would give the command-line model a tool, a file, a server or a way past a prompt.
_FORBIDDEN = ("--dangerously-skip-permissions", "--allowedTools", "--allowed-tools",
              "--add-dir", "--mcp-config", "--plugin-dir", "--settings", "--permission-prompt-tool",
              "--ide", "--chrome")
# Flags that must stay, with the value each must have (None: a switch with no value).
_REQUIRED = {"--tools": "", "--setting-sources": "", "--strict-mcp-config": None,
             "--disable-slash-commands": None, "--permission-mode": "dontAsk"}


def _assert_tool_free(args: list[str]) -> None:
    """Every tool-disabling flag is present with its value, and no tool-enabling flag is."""
    for flag in _FORBIDDEN:
        assert not any(a == flag or a.startswith(flag + "=") for a in args), flag
    for flag, value in _REQUIRED.items():
        assert flag in args, f"{flag} was removed"
        if value is not None:
            assert args[args.index(flag) + 1] == value, f"{flag} changed"
    assert args.count("--permission-mode") == 1 and args.count("--tools") == 1


def test_claude_code_assistant_runs_with_every_tool_off(tmp_path) -> None:
    """The assistant's Claude Code command has no tools, settings, servers or skills."""
    engine = ClaudeCodeEngine(Settings(_env_file=None, data_dir=tmp_path), enabled=True)
    _assert_tool_free(engine.command("claude", "sonnet", None))
    _assert_tool_free(engine.command("claude", "opus", "00000000-0000-4000-8000-000000000001"))


def test_claude_code_bulk_calls_run_with_every_tool_off() -> None:
    """The judging and writing calls through Claude Code are tool-free too."""
    _assert_tool_free(build_command("claude", "haiku", None))
    _assert_tool_free(build_command("claude", "sonnet", {"type": "object"}))


def test_the_tool_check_itself_catches_a_tool_enabling_flag() -> None:
    """The check fails on an added tool flag and on a removed tool-disabling flag."""
    good = build_command("claude", "haiku", None)
    with pytest.raises(AssertionError):
        _assert_tool_free([*good, "--allowedTools", "Bash"])
    with pytest.raises(AssertionError):
        _assert_tool_free([a for a in good if a != "--strict-mcp-config"])


def test_codex_is_unavailable_whatever_its_switch_says(tmp_path, monkeypatch) -> None:
    """Codex cannot run without file access, so it reports itself unavailable and never starts."""
    monkeypatch.setattr(codex_cli, "find_codex", lambda: "codex")

    def refuse(*args, **kwargs):
        raise AssertionError("the codex process must never start")

    monkeypatch.setattr(codex_cli, "ChildProcess", refuse)
    settings = Settings(_env_file=None, data_dir=tmp_path, assist_codex_cli_enabled=True)
    reason = "not supported yet: this engine cannot be run without file access"
    for engine in (CodexCliEngine(settings), CodexCliEngine(settings, enabled=True)):
        assert engine.available() == (False, reason)
        events = list(engine.stream(system="s", messages=[{"role": "user", "content": "q"}],
                                    model="default"))
        assert [(e.kind, e.text) for e in events] == [("error", reason)]
