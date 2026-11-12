# ruff: noqa: F811
"""The Gemini API as an assistant engine: preset, fixed address, key handling, streaming.

Tested with a fake transport only: no Gemini key was available, so nothing here has run against
Google's servers.
"""

import json

import httpx
import pytest
from sqlmodel import Session

from spyglass_service.radar.assist import registry
from spyglass_service.radar.assist.engines.openai_compat import PRESETS

from .test_assist_support import clean_assist_env, db, make_settings, memory_keyring  # noqa: F401

LOCAL_DOWN = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))
BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


@pytest.fixture(autouse=True)
def no_gemini_env(monkeypatch):
    """A Gemini key in the developer's environment must not leak into these tests."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "SPYGLASS_GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def rows(settings, session=None) -> dict[str, dict]:
    return {r["id"]: r for r in registry.list_engines(settings, session, LOCAL_DOWN)}


def test_preset_points_at_googles_openai_compatible_address():
    preset = PRESETS["gemini"]
    assert preset["label"] == "Google Gemini API" and preset["kind"] == "api"
    assert preset["base_url"].rstrip("/") == BASE and preset["key_required"] is True


def test_engine_is_listed_without_a_key_and_says_so(tmp_path, memory_keyring):
    row = rows(make_settings(tmp_path))["gemini"]
    assert row["available"] is False and row["reason"] == "No API key set"
    assert row["needs_key"] is True and row["has_key"] is False


def test_models_are_one_strong_and_one_fast(tmp_path, memory_keyring):
    ids = [m["id"] for m in rows(make_settings(tmp_path))["gemini"]["models"]]
    # "auto" (the cheaper model for simple turns) is offered last, after the strong and the fast one.
    assert ids == ["gemini-4-carbon", "gemini-3.8-flash", "auto"]


def test_environment_key_makes_it_available(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setenv("GEMINI_API_KEY", "g-env")
    row = rows(make_settings(tmp_path))["gemini"]
    assert row["available"] and row["key_source"] == "env"


def test_google_api_key_name_also_works(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-env")
    assert rows(make_settings(tmp_path))["gemini"]["available"]


def test_a_typed_in_key_goes_to_the_keyring_only(tmp_path, db, memory_keyring):
    settings = make_settings(tmp_path)
    with Session(db) as session:
        row = registry.configure_engine(settings, session, "gemini", api_key="g-typed",
                                        transport=LOCAL_DOWN)
    assert row["available"] and row["key_source"] == "keyring"
    assert memory_keyring.store[("spyglass", "gemini")] == "g-typed"
    assert "g-typed" not in json.dumps(row)


def test_the_address_cannot_be_changed(tmp_path, db, memory_keyring):
    assert registry.address_is_editable("gemini") is False
    with Session(db) as session, pytest.raises(registry.ForbiddenSetting):
        registry.configure_engine(make_settings(tmp_path), session, "gemini",
                                  base_url="https://evil.example/v1", transport=LOCAL_DOWN)


def test_a_stored_address_is_ignored(tmp_path, memory_keyring):
    assert registry.effective_base_url("gemini", {"base_url": "https://evil.example/v1"}) \
        .rstrip("/") == BASE


def test_streams_an_answer_from_the_chat_completions_path(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setenv("GEMINI_API_KEY", "g-env")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        chunk = {"choices": [{"delta": {"content": "Hello"}}]}
        return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    engine = registry.get_engine(make_settings(tmp_path), "gemini",
                                 transport=httpx.MockTransport(handler))
    events = list(engine.stream(system="s", messages=[{"role": "user", "content": "hi"}],
                                model="gemini-3.8-flash"))
    assert [e.kind for e in events] == ["delta", "done"]
    assert events[0].text == "Hello"
    request = seen[0]
    assert str(request.url) == BASE + "/chat/completions"
    assert request.headers["authorization"] == "Bearer g-env"
    assert json.loads(request.content)["model"] == "gemini-3.8-flash"
