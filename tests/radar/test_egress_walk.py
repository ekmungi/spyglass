"""Walk the real client-construction paths with fake secrets and record every request.

Every httpx request in the process goes through `httpx.HTTPTransport.handle_request`, which is
replaced here by a recorder that answers locally. Each code path that attaches a secret is run as
it runs in the service. The test then asserts that no fake secret value appears in any request
to a host it is not bound to, and that each secret did reach its own host (so the walk is real).
"""

import httpx
import pytest

from spyglass_service import openrouter
from spyglass_service.collectors import raindrop
from spyglass_service.config import Settings
from spyglass_service.fetch_rungs import make_jina_rung
from spyglass_service.radar.assist import registry, secrets_store
from spyglass_service.radar.assist.engines.openai_compat import OpenAICompatEngine, clear_probe_cache
from spyglass_service.radar.egress import SECRET_HOSTS, SecretDestinationError
from spyglass_service.radar.sources import _common, gmail, slack

FAKES = {
    "openrouter_api_key": ("SPYGLASS_OPENROUTER_API_KEY", "fake-or-7c1f9a2b3d"),
    "anthropic_api_key": ("SPYGLASS_ANTHROPIC_API_KEY", "fake-an-5e8d7c6b4a"),
    "openai_api_key": ("SPYGLASS_OPENAI_API_KEY", "fake-oa-1a2b3c4d5e"),
    "gemini_api_key": ("SPYGLASS_GEMINI_API_KEY", "fake-gem-9f8e7d6c5b"),
    "slack_bot_token": ("SPYGLASS_SLACK_BOT_TOKEN", "fake-xoxb-99887766"),
    "raindrop_token": ("SPYGLASS_RAINDROP_TOKEN", "fake-rd-44556677"),
    "gmail_app_password": ("SPYGLASS_GMAIL_APP_PASSWORD", "fake-gm-pw-112233"),
    "jina_api_key": ("SPYGLASS_JINA_API_KEY", "fake-jina-abcdef12"),
}
CUSTOM_KEY = "fake-custom-key-0001"
CUSTOM_HOST = "models.lab.example"
JSON_BODY = {"choices": [{"message": {"content": "{}"}}], "items": [], "ok": True,
             "messages": [], "data": [], "has_more": False, "item": {"_id": 1}}


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Replace the network with a recorder; every request is kept and answered locally."""
    seen: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        if request.url.host in ("r.jina.ai",) or request.url.host.endswith("example.com"):
            return httpx.Response(200, text="<html><title>A page title here</title></html>",
                                  headers={"content-type": "text/html"}, request=request)
        return httpx.Response(200, json=JSON_BODY, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return seen


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    """Settings carrying only fake secrets (from the environment, never from a .env file)."""
    for env, value in FAKES.values():
        monkeypatch.setenv(env, value)
    monkeypatch.setattr(secrets_store, "get_secret",
                        lambda engine_id: CUSTOM_KEY if engine_id == "custom-lab" else None)
    clear_probe_cache()
    return Settings(_env_file=None, data_dir=tmp_path, gmail_address="reader@example.org",
                    slack_capture_channel="C123", jina_enabled=True)


def _drain(engine, **kwargs) -> list:
    """Consume an engine's stream; a refusal raised inside counts as an outcome, not a leak."""
    try:
        return list(engine.stream(system="sys", messages=[{"role": "user", "content": "hi"}],
                                  model="m", **kwargs))
    except SecretDestinationError:
        return []


def _blob(request: httpx.Request) -> str:
    """Everything a request carries: address, every header value and the body."""
    headers = " ".join(f"{k}: {v}" for k, v in request.headers.items())
    return f"{request.url} {headers} {request.content.decode('utf-8', 'replace')}"


def _walk(settings: Settings) -> None:
    """Run every code path that attaches a secret, as the service runs it."""
    openrouter.chat_json([{"role": "user", "content": "x"}], {"name": "s", "schema": {}},
                         model="m", api_key=settings.openrouter_api_key)
    doc = {"version": 1, "engines": {"custom-lab": {"base_url": f"https://{CUSTOM_HOST}/v1",
                                                    "enabled": True}}}
    for engine_id in ("openrouter", "openai", "gemini", "anthropic", "custom-lab"):
        engine = registry.build_engine(settings, engine_id, doc)
        _drain(engine)
        if hasattr(engine, "_probe"):
            engine._probe()
    slack._http_transport(settings.slack_bot_token)(
        "https://slack.com/api/conversations.history", {"channel": "C123"})
    raindrop.RaindropCollector(token=settings.raindrop_token).collect()
    raindrop.resolve_processed_collection(settings.raindrop_token)
    make_jina_rung(settings.jina_api_key)("https://example.com/article")
    _common.http_get_bytes("https://example.com/feed")


def _assert_bound(seen: list[httpx.Request]) -> None:
    """No fake value reached a host it is not bound to; each reached its own host."""
    reached: set[str] = set()
    for request in seen:
        blob, host = _blob(request), request.url.host
        for name, (_env, value) in FAKES.items():
            if value in blob:
                assert host in SECRET_HOSTS[name], f"{name} was sent to {host}"
                reached.add(name)
        if CUSTOM_KEY in blob:
            assert host == CUSTOM_HOST, f"the custom key was sent to {host}"
            reached.add("custom")
    expected = set(FAKES) - {"gmail_app_password"} | {"custom"}
    assert reached == expected


def test_no_fake_secret_reaches_a_host_it_is_not_bound_to(recorder, settings) -> None:
    """The real paths send every secret to its own host and nowhere else."""
    _walk(settings)
    _assert_bound(recorder)


def test_a_misconfigured_engine_address_never_receives_the_key(recorder, settings) -> None:
    """An engine whose address was tampered with refuses the request before sending it."""
    for engine_id, secret in (("openrouter", "openrouter_api_key"), ("openai", "openai_api_key")):
        engine = OpenAICompatEngine(id=engine_id, label="x", kind="api",
                                    base_url="https://evil.example/v1",
                                    api_key=getattr(settings, secret))
        events = _drain(engine)
        assert not any(e.kind == "delta" for e in events)
        assert engine._probe() is None
    assert not any(r.url.host == "evil.example" for r in recorder)


def test_gmail_password_goes_only_to_the_gmail_server(monkeypatch, settings) -> None:
    """The IMAP login happens only against imap.gmail.com; another host is refused first."""
    opened: list[str] = []

    class FakeImap:
        """Stands in for imaplib.IMAP4_SSL and records where it would connect."""

        def __init__(self, host: str, port: int, timeout: float) -> None:
            opened.append(host)

        def login(self, user: str, password: str) -> None:
            """Accept any login."""

    monkeypatch.setattr(gmail.imaplib, "IMAP4_SSL", FakeImap)
    gmail._connect(settings)
    assert opened == ["imap.gmail.com"]
    monkeypatch.setattr(gmail, "IMAP_HOST", "imap.evil.example")
    with pytest.raises(SecretDestinationError):
        gmail._connect(settings)
    assert opened == ["imap.gmail.com"]


def test_raindrop_refuses_an_injected_client_aimed_elsewhere(monkeypatch, settings) -> None:
    """Even with a caller-supplied client, the token is checked against the address first."""
    monkeypatch.setattr(raindrop, "_API_URL", "https://evil.example/rest/v1/raindrops/0")
    sent: list[str] = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: sent.append(str(r.url)) or httpx.Response(200, json={"items": []})))
    with pytest.raises(SecretDestinationError):
        raindrop.RaindropCollector(token=settings.raindrop_token, client=client).collect()
    client.close()
    assert sent == []
