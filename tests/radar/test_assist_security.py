# ruff: noqa: F811
"""Security regressions for the assistant: where a key may be sent, and what reaches a command line."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.radar.api import assist as assist_api
from spyglass_service.radar.assist import registry
from spyglass_service.radar.assist.engines import claude_code, codex_cli
from spyglass_service.radar.assist.engines.process import ChildProcess
from spyglass_service.radar.models import RadarDoc, dumps

from .test_assist_support import clean_assist_env, db, make_settings, memory_keyring  # noqa: F401

LOCAL_DOWN = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))
HOSTILE = "https://collector.attacker.example/v1"
ENV_KEY = "sk-or-SECRET-123"


def recording_transport(seen: list) -> httpx.MockTransport:
    """A transport that records (url, authorization) and answers with an empty event stream."""
    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and finish the stream at once."""
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, text="data: [DONE]\n\n")
    return httpx.MockTransport(handler)


def ask(engine) -> None:
    """Run one turn against an engine, discarding the events."""
    list(engine.stream(system="x", messages=[{"role": "user", "content": "hi"}], model="m"))


def store_doc(db, engines: dict) -> None:
    """Write an engines document straight into the database, as a hostile earlier write would."""
    with Session(db) as session:
        session.add(RadarDoc(key=registry.DOC_KEY, body=dumps({"version": 1, "engines": engines})))
        session.commit()


# ---- defect 7: the preset key must not follow a changed address -------------------------------

@pytest.mark.parametrize("engine_id", ["openrouter", "openai", "anthropic", "claude_code", "codex_cli"])
def test_base_url_cannot_be_set_on_an_engine_with_a_fixed_address(tmp_path, db, memory_keyring, engine_id):
    settings = make_settings(tmp_path)
    with Session(db) as session, pytest.raises(registry.ForbiddenSetting):
        registry.configure_engine(settings, session, engine_id, base_url=HOSTILE, transport=LOCAL_DOWN)
        pytest.fail("the address must be refused")


def test_put_with_base_url_on_openrouter_is_422(tmp_path, db, memory_keyring):
    app = FastAPI()
    app.include_router(assist_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings, app.state.assist_transport = (
        db, make_settings(tmp_path), LOCAL_DOWN)
    response = TestClient(app).put("/api/radar/engines/openrouter", json={"base_url": HOSTILE})
    assert response.status_code == 422


def test_stored_hostile_base_url_on_openrouter_is_ignored_at_use_time(tmp_path, db, memory_keyring,
                                                                      monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", ENV_KEY)
    store_doc(db, {"openrouter": {"base_url": HOSTILE}})
    seen: list = []
    with Session(db) as session:
        engine = registry.get_engine(make_settings(tmp_path), "openrouter", session,
                                     recording_transport(seen))
        row = next(r for r in registry.list_engines(make_settings(tmp_path), session, LOCAL_DOWN)
                   if r["id"] == "openrouter")
    ask(engine)
    assert seen and all(url.startswith("https://openrouter.ai/") for url, _ in seen)
    assert row["base_url"] == "https://openrouter.ai/api/v1"


def test_custom_engine_uses_its_own_key_never_the_environment_key(tmp_path, db, memory_keyring,
                                                                  monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", ENV_KEY)
    settings = make_settings(tmp_path)
    seen: list = []
    with Session(db) as session:
        registry.configure_engine(settings, session, "custom-box", base_url="https://box.example/v1",
                                  api_key="own-key", transport=LOCAL_DOWN)
        ask(registry.get_engine(settings, "custom-box", session, recording_transport(seen)))
    assert seen[0][1] == "Bearer own-key"
    assert all(ENV_KEY not in (auth or "") for _, auth in seen)


def test_custom_engine_without_own_key_sends_no_authorization(tmp_path, db, memory_keyring, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", ENV_KEY)
    settings = make_settings(tmp_path)
    seen: list = []
    with Session(db) as session:
        registry.configure_engine(settings, session, "custom-box", base_url="https://box.example/v1",
                                  transport=LOCAL_DOWN)
        ask(registry.get_engine(settings, "custom-box", session, recording_transport(seen)))
    assert seen and seen[0][1] is None


@pytest.mark.parametrize(("url", "sent"), [
    ("http://203.0.113.9:8000/v1", False),
    ("http://box.example/v1", False),
    ("https://box.example/v1", True),
    ("http://127.0.0.1:8000/v1", True),
    ("http://localhost:8000/v1", True),
    ("http://[::1]:8000/v1", True),
])
def test_key_is_never_sent_over_plain_http_to_a_remote_host(tmp_path, db, memory_keyring, url, sent):
    settings = make_settings(tmp_path)
    seen: list = []
    with Session(db) as session:
        registry.configure_engine(settings, session, "custom-box", base_url=url, api_key="own-key",
                                  transport=LOCAL_DOWN)
        ask(registry.get_engine(settings, "custom-box", session, recording_transport(seen)))
    assert (seen[0][1] == "Bearer own-key") is sent


def test_custom_address_must_be_http_or_https(tmp_path, db, memory_keyring):
    with Session(db) as session:
        for bad in ("file:///etc/passwd", "ftp://x/v1", "javascript:alert(1)", "http://"):
            with pytest.raises(registry.ConfigError):
                registry.configure_engine(make_settings(tmp_path), session, "custom-a", base_url=bad,
                                          transport=LOCAL_DOWN)


def test_stored_custom_address_with_a_bad_scheme_gives_no_engine(tmp_path, db, memory_keyring):
    store_doc(db, {"custom-x": {"base_url": "file:///etc/passwd"}})
    with Session(db) as session:
        assert registry.get_engine(make_settings(tmp_path), "custom-x", session) is None


def test_local_server_address_can_still_be_changed(tmp_path, db, memory_keyring):
    with Session(db) as session:
        row = registry.configure_engine(make_settings(tmp_path), session, "ollama",
                                        base_url="http://127.0.0.1:9999/v1", transport=LOCAL_DOWN)
    assert row["base_url"] == "http://127.0.0.1:9999/v1"


def test_changing_the_address_drops_the_stored_key_unless_a_new_one_comes_with_it(
        tmp_path, db, memory_keyring):
    settings = make_settings(tmp_path)
    with Session(db) as session:
        registry.configure_engine(settings, session, "custom-box", base_url="https://a.example/v1",
                                  api_key="own-key", transport=LOCAL_DOWN)
        registry.configure_engine(settings, session, "custom-box", base_url="https://b.example/v1",
                                  transport=LOCAL_DOWN)
        assert ("spyglass", "custom-box") not in memory_keyring.store
        registry.configure_engine(settings, session, "custom-box", base_url="https://c.example/v1",
                                  api_key="new-key", transport=LOCAL_DOWN)
    assert memory_keyring.store[("spyglass", "custom-box")] == "new-key"


# ---- defect 16: model, engine and session ids must be inert on a command line ------------------

BAD_MODELS = ["haiku&calc", "haiku|calc", "a b", "-p", "--dangerous", "x\ny", 'a"b', "a^b", "a%PATH%",
              "", "x" * 121]


@pytest.mark.parametrize("model", BAD_MODELS[:-2])
def test_api_refuses_a_model_that_is_not_a_plain_name(tmp_path, db, memory_keyring, model):
    app = FastAPI()
    app.include_router(assist_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings, app.state.assist_transport = (
        db, make_settings(tmp_path), LOCAL_DOWN)
    client = TestClient(app)
    thread = client.post("/api/radar/threads", json={}).json()["thread"]["id"]
    response = client.post(f"/api/radar/threads/{thread}/messages",
                           json={"content": "hi", "engine": "claude_code", "model": model})
    if model == "":
        assert response.status_code != 422  # an empty model means "the engine's default"
    else:
        assert response.status_code == 422


def test_api_refuses_a_too_long_model_and_an_unknown_or_odd_engine(tmp_path, db, memory_keyring):
    app = FastAPI()
    app.include_router(assist_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings, app.state.assist_transport = (
        db, make_settings(tmp_path), LOCAL_DOWN)
    client = TestClient(app)
    thread = client.post("/api/radar/threads", json={}).json()["thread"]["id"]
    path = f"/api/radar/threads/{thread}/messages"
    assert client.post(path, json={"content": "hi", "model": "x" * 121}).status_code == 422
    assert client.post(path, json={"content": "hi", "engine": "nope"}).status_code == 422
    assert client.post(path, json={"content": "hi", "engine": "a&b"}).status_code == 422


@pytest.mark.parametrize("model", ["haiku&calc", "-p", "a b", 'a"b'])
def test_command_builders_refuse_a_bad_model(tmp_path, model):
    settings = make_settings(tmp_path)
    with pytest.raises(ValueError):
        claude_code.ClaudeCodeEngine(settings, enabled=True).command("claude", model, None)
    with pytest.raises(ValueError):
        codex_cli.CodexCliEngine(settings, enabled=True).command("codex", model, None)


def test_command_builders_accept_the_real_model_names(tmp_path):
    settings = make_settings(tmp_path)
    args = claude_code.ClaudeCodeEngine(settings, enabled=True).command(
        "claude", "claude-opus-4-1[1m]", "0b9c1d52-aaaa-bbbb-cccc-123456789012")
    assert "claude-opus-4-1[1m]" in args and "--resume" in args
    assert "--model" not in codex_cli.CodexCliEngine(settings, enabled=True).command("codex", "default", None)


@pytest.mark.parametrize("session", ["--evil", "a b", "x&y", "a;b", "-1", "x" * 200])
def test_command_builders_refuse_a_bad_session_id(tmp_path, session):
    settings = make_settings(tmp_path)
    with pytest.raises(ValueError):
        claude_code.ClaudeCodeEngine(settings, enabled=True).command("claude", "haiku", session)
    with pytest.raises(ValueError):
        codex_cli.CodexCliEngine(settings, enabled=True).command("codex", "default", session)


def test_stream_reports_a_bad_model_without_starting_a_process(tmp_path, monkeypatch):
    started: list = []
    monkeypatch.setattr(claude_code, "ChildProcess", lambda *a, **k: started.append(a))
    monkeypatch.setattr(claude_code, "find_claude", lambda settings: "claude")
    engine = claude_code.ClaudeCodeEngine(make_settings(tmp_path), enabled=True)
    events = list(engine.stream(system="s", messages=[{"role": "user", "content": "q"}],
                                model="haiku&calc"))
    assert [e.kind for e in events] == ["error"] and not started


def test_stream_ignores_a_bad_stored_session_id_and_starts_fresh(tmp_path, monkeypatch):
    commands: list = []

    class Child:
        """Records its command; ends at once without output."""

        stderr_tail = ""

        def __init__(self, command, **kwargs):
            commands.append(command)

        def lines(self, **kwargs):
            return iter(())

        def close(self):
            return None

    monkeypatch.setattr(claude_code, "ChildProcess", Child)
    monkeypatch.setattr(claude_code, "find_claude", lambda settings: "claude")
    engine = claude_code.ClaudeCodeEngine(make_settings(tmp_path), enabled=True)
    list(engine.stream(system="s", messages=[{"role": "user", "content": "q"}], model="haiku",
                       session="--evil"))
    assert commands and all("--evil" not in c and "--resume" not in c for c in commands)


@pytest.mark.parametrize("command", [
    ["tool.cmd", "--model", "a&calc"], ["tool.BAT", "x|y"], ["C:\\bin\\tool.cmd", "a>b"],
    ["tool.cmd", "50%"], ["tool.cmd", 'a"b'], ["tool.cmd", "a\nb"], ["tool.cmd", "a^b"],
])
def test_child_process_refuses_cmd_metacharacters_for_a_batch_file(tmp_path, command):
    with pytest.raises(ValueError, match="metacharacters"):
        ChildProcess(command, cwd=tmp_path, env={}, stdin_text="")


def test_child_process_allows_plain_arguments_for_a_batch_file_check(tmp_path):
    from spyglass_service.radar.assist.engines.safe_args import assert_cmd_safe
    assert_cmd_safe(["tool.cmd", "-p", "--model", "haiku", "it's fine, really."])
    assert_cmd_safe(["tool.exe", "a&b"])  # a real executable gets no shell, so nothing to refuse
