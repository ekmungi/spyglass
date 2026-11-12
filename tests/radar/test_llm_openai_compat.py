"""Tests for the OpenAI-compatible bulk JSON call (fake transport only; no network, no model)."""

import json

import httpx
import pytest

from spyglass_service.radar import llm_chain
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.llm_openai_compat import (
    GEMINI_BASE_URL,
    chat_json,
    gemini_chat_json,
)

SCHEMA = {"name": "verdict", "schema": {"type": "object", "required": ["score"],
                                        "properties": {"score": {"type": "integer"}}}}
MESSAGES = [{"role": "system", "content": "Judge."}, {"role": "user", "content": "Item"}]


def reply(content: str, status: int = 200) -> httpx.Response:
    """A chat-completions response carrying `content`."""
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


class Server:
    """A scripted endpoint: records requests, answers from a list of responses."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def call(server: Server, **kw):
    return chat_json(MESSAGES, SCHEMA, base_url=GEMINI_BASE_URL, api_key="secret-key",
                     model="m", label="Gemini", transport=server.transport, sleep=lambda s: None,
                     **kw)


def test_returns_the_parsed_object_and_sends_schema_model_and_bearer_key():
    server = Server(reply('{"score": 7}'))
    assert call(server) == {"score": 7}
    request = server.requests[0]
    assert str(request.url) == GEMINI_BASE_URL.rstrip("/") + "/chat/completions"
    assert request.headers["authorization"] == "Bearer secret-key"
    body = json.loads(request.content)
    assert body["model"] == "m" and body["messages"] == MESSAGES
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "verdict"
    assert body["response_format"]["json_schema"]["schema"]["required"] == ["score"]


def test_tolerates_a_fenced_reply():
    assert call(Server(reply('```json\n{"score": 3}\n```'))) == {"score": 3}


def test_unusable_reply_is_a_value_error_not_unavailable():
    with pytest.raises(ValueError):
        call(Server(reply("I cannot do that.")))
    with pytest.raises(ValueError) as caught:
        call(Server(reply('{"other": 1}')))
    assert "score" in str(caught.value)


@pytest.mark.parametrize("status,words", [(401, "rejected"), (403, "rejected"),
                                           (402, "credit"), (429, "limit")])
def test_account_problems_are_unavailable_with_a_plain_message(status, words):
    with pytest.raises(LlmUnavailable) as caught:
        call(Server(httpx.Response(status, json={"error": {"message": "nope"}})))
    assert words in str(caught.value).lower()
    assert "secret-key" not in str(caught.value)


def test_a_server_error_is_retried_then_unavailable():
    server = Server(httpx.Response(503), httpx.Response(503), httpx.Response(503))
    with pytest.raises(LlmUnavailable):
        call(server)
    assert len(server.requests) == 3


def test_a_server_error_then_success_recovers():
    server = Server(httpx.Response(503), reply('{"score": 1}'))
    assert call(server) == {"score": 1}


def test_network_failure_is_unavailable():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(LlmUnavailable):
        chat_json(MESSAGES, SCHEMA, base_url=GEMINI_BASE_URL, api_key="k", model="m",
                  label="Gemini", transport=httpx.MockTransport(boom), sleep=lambda s: None)


def test_a_rejected_schema_falls_back_to_plain_json_mode_with_the_schema_in_the_prompt():
    server = Server(httpx.Response(400, json={"error": {"message": "bad schema"}}),
                    reply('{"score": 9}'))
    assert call(server) == {"score": 9}
    second = json.loads(server.requests[1].content)
    assert second["response_format"] == {"type": "json_object"}
    assert "score" in second["messages"][0]["content"] and "JSON Schema" in second["messages"][0]["content"]


def test_a_request_rejected_in_both_modes_is_a_value_error():
    server = Server(httpx.Response(400), httpx.Response(400))
    with pytest.raises(ValueError):
        call(server)


def test_the_key_is_only_sent_over_https_to_an_allowed_host():
    server = Server(reply('{"score": 1}'))
    with pytest.raises(LlmUnavailable):
        chat_json(MESSAGES, SCHEMA, base_url="http://generativelanguage.googleapis.com/v1beta/openai/",
                  api_key="k", model="m", label="Gemini", transport=server.transport,
                  allowed_hosts={"generativelanguage.googleapis.com"})
    with pytest.raises(LlmUnavailable):
        chat_json(MESSAGES, SCHEMA, base_url="https://evil.example/v1", api_key="k", model="m",
                  label="Gemini", transport=server.transport,
                  allowed_hosts={"generativelanguage.googleapis.com"})
    assert server.requests == []


def test_missing_key_is_unavailable_without_a_request():
    server = Server()
    with pytest.raises(LlmUnavailable):
        chat_json(MESSAGES, SCHEMA, base_url=GEMINI_BASE_URL, api_key="", model="m",
                  label="Gemini", transport=server.transport)
    assert server.requests == []


# ---- the Gemini wrapper --------------------------------------------------------------------

class Settings:
    def __init__(self, key):
        self.gemini_api_key = key


def test_gemini_wrapper_uses_the_settings_key(monkeypatch):
    server = Server(reply('{"score": 2}'))
    out = gemini_chat_json(Settings("g-key"), "gemini-3.8-flash", MESSAGES, SCHEMA,
                           transport=server.transport)
    assert out == {"score": 2}
    assert server.requests[0].headers["authorization"] == "Bearer g-key"
    assert server.requests[0].url.host == "generativelanguage.googleapis.com"


def test_gemini_wrapper_falls_back_to_the_keyring_then_fails_plainly(monkeypatch):
    monkeypatch.setattr(llm_chain, "_stored_key", lambda name: "ring-key" if name == "gemini" else None)
    server = Server(reply('{"score": 2}'))
    gemini_chat_json(Settings(None), "m", MESSAGES, SCHEMA, transport=server.transport)
    assert server.requests[0].headers["authorization"] == "Bearer ring-key"
    monkeypatch.setattr(llm_chain, "_stored_key", lambda name: None)
    with pytest.raises(LlmUnavailable) as caught:
        gemini_chat_json(Settings(None), "m", MESSAGES, SCHEMA, transport=Server().transport)
    assert "Gemini key" in str(caught.value)
