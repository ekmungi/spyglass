# ruff: noqa: F811
"""Tests for the engine registry: availability, defaults, configuration, and key handling."""

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from spyglass_service.radar.api import assist as assist_api
from spyglass_service.radar.assist import registry, secrets_store
from spyglass_service.radar.assist.engines import claude_code
from spyglass_service.radar.models import RadarDoc

from .test_assist_support import clean_assist_env, db, make_settings, memory_keyring  # noqa: F401

LOCAL_DOWN = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))


def configure(settings, session, engine_id, **kw) -> dict:
    """registry.configure_engine with local servers reported as not running (no real network)."""
    kw.setdefault("transport", LOCAL_DOWN)
    return registry.configure_engine(settings, session, engine_id, **kw)


def rows_by_id(settings, session=None, transport=LOCAL_DOWN) -> dict[str, dict]:
    """list_engines keyed by id, with local servers reported as not running."""
    return {r["id"]: r for r in registry.list_engines(settings, session, transport)}


def test_nothing_configured_means_only_off_engines_and_no_default(tmp_path, memory_keyring):
    rows = rows_by_id(make_settings(tmp_path))
    assert list(rows) == list(registry.ENGINE_ORDER)
    assert not any(r["available"] for r in rows.values())
    assert not any(r["is_default"] for r in rows.values())
    assert rows["openrouter"]["reason"] == "No API key set"
    assert "not running" in rows["ollama"]["reason"]
    assert "off" in rows["claude_code"]["reason"].lower()


def test_environment_key_makes_engine_available_and_default(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    rows = rows_by_id(make_settings(tmp_path))
    assert rows["openrouter"]["available"] and rows["openrouter"]["is_default"]
    assert rows["openrouter"]["key_source"] == "env"
    ids = [m["id"] for m in rows["openrouter"]["models"]]
    assert "anthropic/claude-sonnet-5.5" in ids and len(ids) >= 7
    assert rows["openrouter"]["default_model"] == ids[0]


def test_default_engine_follows_the_setting_then_the_order(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setenv("OPENROUTER_API_KEY", "a")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "b")
    chosen = rows_by_id(make_settings(tmp_path, assist_default_engine="anthropic",
                                      assist_default_model="claude-opus-9"))
    assert chosen["anthropic"]["is_default"] and not chosen["openrouter"]["is_default"]
    assert chosen["anthropic"]["default_model"] == "claude-opus-9"
    assert "claude-opus-9" in [m["id"] for m in chosen["anthropic"]["models"]]
    # A chosen engine that is not available falls back to the first available one.
    fallback = rows_by_id(make_settings(tmp_path, assist_default_engine="openai"))
    assert fallback["openrouter"]["is_default"]


def test_keyring_key_counts_and_environment_wins(tmp_path, monkeypatch, memory_keyring):
    secrets_store.set_secret("openai", "sk-from-keyring")
    row = rows_by_id(make_settings(tmp_path))["openai"]
    assert row["available"] and row["key_source"] == "keyring"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert rows_by_id(make_settings(tmp_path))["openai"]["key_source"] == "env"
    assert registry.resolve_key(make_settings(tmp_path), "openai") == ("sk-from-env", "env")


def test_local_engine_available_when_port_answers(tmp_path, memory_keyring):
    up = httpx.MockTransport(lambda req: httpx.Response(200, json={"data": [{"id": "qwen"}]}))
    row = rows_by_id(make_settings(tmp_path), transport=up)["lmstudio"]
    assert row["available"] and row["models"] == [{"id": "qwen", "label": "qwen"}]
    assert row["kind"] == "local"


def test_claude_code_needs_setting_or_switch_and_the_command(tmp_path, monkeypatch, memory_keyring,
                                                             db):
    monkeypatch.setattr(claude_code, "find_claude", lambda s: "claude")
    assert rows_by_id(make_settings(tmp_path))["claude_code"]["available"] is False
    on = rows_by_id(make_settings(tmp_path, assist_claude_code_enabled=True))["claude_code"]
    assert on["available"] and [m["id"] for m in on["models"]][:2] == ["sonnet", "opus"]
    with Session(db) as session:
        configure(make_settings(tmp_path), session, "claude_code", enabled=True)
        assert rows_by_id(make_settings(tmp_path), session)["claude_code"]["available"]
    monkeypatch.setattr(claude_code, "find_claude", lambda s: None)
    gone = rows_by_id(make_settings(tmp_path, assist_claude_code_enabled=True))["claude_code"]
    assert gone["available"] is False and "not found" in gone["reason"]


def test_configure_stores_key_in_keyring_only_and_never_returns_it(tmp_path, db, memory_keyring):
    settings = make_settings(tmp_path)
    with Session(db) as session:
        row = configure(settings, session, "anthropic", api_key="sk-ant-SECRET-9")
        stored = session.exec(select(RadarDoc)).all()
    assert memory_keyring.store[("spyglass", "anthropic")] == "sk-ant-SECRET-9"
    assert row["available"] and row["has_key"] and row["key_source"] == "keyring"
    assert "SECRET" not in json.dumps(row)
    assert all("SECRET" not in d.body for d in stored)


def test_configure_empty_key_removes_it_and_unknown_engine_is_refused(tmp_path, db, memory_keyring):
    settings = make_settings(tmp_path)
    with Session(db) as session:
        configure(settings, session, "openai", api_key="sk-x")
        row = configure(settings, session, "openai", api_key="")
        assert row["available"] is False and ("spyglass", "openai") not in memory_keyring.store
        with pytest.raises(registry.ConfigError, match="Unknown engine"):
            configure(settings, session, "nope", enabled=True)
        with pytest.raises(registry.ConfigError, match="http"):
            configure(settings, session, "ollama", base_url="ftp://x")


def test_disabled_engine_is_unavailable_and_extra_models_are_listed(tmp_path, db, memory_keyring,
                                                                    monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    settings = make_settings(tmp_path)
    with Session(db) as session:
        configure(settings, session, "openrouter", models=["acme/model-1"],
                                  default_model="acme/model-1")
        row = rows_by_id(settings, session)["openrouter"]
        assert "acme/model-1" in [m["id"] for m in row["models"]]
        assert row["default_model"] == "acme/model-1"
        off = configure(settings, session, "openrouter", enabled=False)
    assert off["available"] is False and off["reason"] == "Switched off"


def test_custom_engine_lifecycle(tmp_path, db, memory_keyring):
    settings = make_settings(tmp_path)
    with Session(db) as session:
        row = configure(settings, session, "custom-vllm", base_url="http://10.0.0.5:8000/v1",
                                        label="Office vLLM", models=["m-1"], api_key="tok")
        assert row["custom"] and row["available"] and row["label"] == "Office vLLM"
        assert [m["id"] for m in row["models"]] == ["m-1"]
        assert registry.get_engine(settings, "custom-vllm", session) is not None
        assert registry.remove_custom(session, "custom-vllm") is True
        assert ("spyglass", "custom-vllm") not in memory_keyring.store
        assert registry.get_engine(settings, "custom-vllm", session) is None
        assert registry.remove_custom(session, "custom-vllm") is False
        assert registry.remove_custom(session, "openrouter") is False


def test_get_engine_unknown_id_is_none(tmp_path, memory_keyring):
    assert registry.get_engine(make_settings(tmp_path), "bogus") is None


def test_secret_store_failures_are_reported_cleanly(monkeypatch):
    import keyring.errors

    def boom(*a):
        raise keyring.errors.KeyringError("no backend")

    monkeypatch.setattr("keyring.get_password", boom)
    monkeypatch.setattr("keyring.set_password", boom)
    assert secrets_store.get_secret("x") is None
    with pytest.raises(secrets_store.SecretStoreError):
        secrets_store.set_secret("x", "v")


def app_for(db, settings, transport=LOCAL_DOWN) -> TestClient:
    """A tiny app with only the assistant router."""
    app = FastAPI()
    app.include_router(assist_api.router, prefix="/api/radar")
    app.state.engine, app.state.settings, app.state.assist_transport = db, settings, transport
    return TestClient(app)


def test_engines_api_never_contains_a_key(tmp_path, db, memory_keyring):
    client = app_for(db, make_settings(tmp_path))
    put = client.put("/api/radar/engines/openai", json={"api_key": "sk-LEAKCHECK-123"})
    assert put.status_code == 200 and put.json()["available"] is True
    listing = client.get("/api/radar/engines")
    assert listing.status_code == 200
    assert "LEAKCHECK" not in put.text and "LEAKCHECK" not in listing.text
    assert memory_keyring.store[("spyglass", "openai")] == "sk-LEAKCHECK-123"
    assert "api_key" not in json.dumps(listing.json())


def test_engines_api_errors(tmp_path, db, memory_keyring):
    client = app_for(db, make_settings(tmp_path))
    assert client.put("/api/radar/engines/nope", json={"enabled": True}).status_code == 404
    assert client.put("/api/radar/engines/ollama", json={"base_url": "ftp://x"}).status_code == 400
    assert client.put("/api/radar/engines/ollama", json={"bogus": 1}).status_code == 422
    assert client.delete("/api/radar/engines/custom-none").status_code == 404
    made = client.put("/api/radar/engines/custom-a", json={"base_url": "http://h/v1"})
    assert made.status_code == 200
    assert client.delete("/api/radar/engines/custom-a").status_code == 204


def test_engines_api_reports_unavailable_keyring(tmp_path, db, monkeypatch):
    import keyring.errors

    def boom(*a):
        raise keyring.errors.KeyringError("none")

    monkeypatch.setattr("keyring.set_password", boom)
    client = app_for(db, make_settings(tmp_path))
    assert client.put("/api/radar/engines/openai", json={"api_key": "k"}).status_code == 503
