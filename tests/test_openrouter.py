# Tests for the OpenRouter structured-output JSON client (openrouter.py).
import json
import httpx
import pytest
from spyglass_service.openrouter import chat_json, OpenRouterError

def _ok_handler(payload):
    def handler(request):
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "deepseek/deepseek-v4-flash"
        assert body["response_format"]["type"] == "json_schema"
        # stable-prefix-first: system message present and first
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(payload)}}]
        })
    return httpx.MockTransport(handler)

SCHEMA = {"name": "r", "schema": {"type": "object", "properties": {"x": {"type": "integer"}}}}

def test_returns_parsed_json():
    t = _ok_handler({"x": 7})
    out = chat_json([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}],
                    SCHEMA, model="deepseek/deepseek-v4-flash", api_key="sk-test", transport=t)
    assert out == {"x": 7}

def test_missing_key_raises():
    with pytest.raises(OpenRouterError):
        chat_json([], SCHEMA, model="m", api_key="", transport=None)

def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("spyglass_service.openrouter.time.sleep", lambda *_: None)
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"error": "rate"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"x\": 1}"}}]})
    out = chat_json([{"role": "user", "content": "u"}], SCHEMA, model="m",
                    api_key="sk-test", transport=httpx.MockTransport(handler), max_retries=3)
    assert out == {"x": 1} and calls["n"] == 2

def test_exhausted_retries_raises(monkeypatch):
    monkeypatch.setattr("spyglass_service.openrouter.time.sleep", lambda *_: None)
    t = httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(OpenRouterError):
        chat_json([{"role": "user", "content": "u"}], SCHEMA, model="m",
                  api_key="sk-test", transport=t, max_retries=2)
