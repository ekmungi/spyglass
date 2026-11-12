"""Tests for the HTTP assistant engines: SSE parsing, OpenAI-compatible and Anthropic streaming."""

import json

import httpx

from spyglass_service.radar.assist.engines.anthropic_api import AnthropicEngine
from spyglass_service.radar.assist.engines.base import StreamEvent, http_error_message
from spyglass_service.radar.assist.engines.openai_compat import OpenAICompatEngine
from spyglass_service.radar.assist.engines.sse import iter_sse

from .test_assist_support import clean_assist_env, delta, split_response, sse_body  # noqa: F401

MESSAGES = [{"role": "user", "content": "hi"}]


def run(engine, **kw) -> list[StreamEvent]:
    """Collect every event of one turn."""
    return list(engine.stream(system="sys", messages=MESSAGES, model="m", **kw))


def compat(handler, **kw) -> OpenAICompatEngine:
    """An OpenAI-compatible engine whose HTTP calls go to `handler`.

    The address is OpenRouter's real one: an OpenRouter key may only be sent to openrouter.ai.
    """
    return OpenAICompatEngine(id="openrouter", label="OpenRouter", kind="api",
                              base_url="https://openrouter.ai/api/v1", api_key="sk-secret-1234",
                              transport=httpx.MockTransport(handler), **kw)


def texts(events: list[StreamEvent]) -> str:
    """The joined delta text."""
    return "".join(e.text for e in events if e.kind == "delta")


def test_iter_sse_skips_comments_joins_data_and_yields_unterminated_event():
    lines = [": ping\n", "event: foo\n", "data: a\n", "data: b\n", "\n", "data: tail"]
    assert list(iter_sse(lines)) == [("foo", "a\nb"), ("message", "tail")]


def test_iter_sse_ignores_blank_events():
    assert list(iter_sse(["\n", "\n", ": x\n", "\n"])) == []


def test_openai_stream_joins_deltas_and_ends_with_done():
    body = sse_body(delta("Hel"), delta("lo"), {"choices": [{"delta": {}}]}, comments=True)
    events = run(compat(lambda req: httpx.Response(200, content=body)))
    assert texts(events) == "Hello"
    assert events[-1] == StreamEvent.done()


def test_openai_stream_survives_chunks_that_split_lines():
    body = sse_body(delta("Hello"), delta(" wörld"), comments=True)
    events = run(compat(lambda req: split_response(body, size=5)))
    assert texts(events) == "Hello wörld"
    assert events[-1].kind == "done"


def test_openai_request_shape_and_key_only_in_header():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=sse_body(delta("x")))

    run(compat(handler))
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-secret-1234"
    assert seen["body"]["stream"] is True
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert "sk-secret" not in json.dumps(seen["body"])


def test_openai_error_status_gives_short_message_without_key():
    body = json.dumps({"error": {"message": "Invalid key sk-secret-1234 provided"}})
    events = run(compat(lambda req: httpx.Response(401, content=body)))
    assert [e.kind for e in events] == ["error"]
    assert "HTTP 401" in events[0].text and "OpenRouter" in events[0].text


def test_openai_mid_stream_error_object_becomes_error_event():
    body = sse_body(delta("par"), {"error": {"message": "upstream failed"}})
    events = run(compat(lambda req: httpx.Response(200, content=body)))
    assert texts(events) == "par"
    assert events[-1].kind == "error" and "upstream failed" in events[-1].text


def test_openai_empty_answer_is_an_error():
    events = run(compat(lambda req: httpx.Response(200, content=sse_body())))
    assert events[-1].kind == "error"


def test_openai_connection_failure_is_an_error_not_an_exception():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    events = run(compat(handler))
    assert events[-1].kind == "error" and "reach" in events[-1].text


def test_openai_timeout_is_an_error():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    assert "timed out" in run(compat(handler))[-1].text


def test_closing_the_stream_early_closes_the_http_response():
    closed = []

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            try:
                for i in range(100):
                    yield f"data: {json.dumps(delta(str(i)))}\n\n".encode()
            finally:
                closed.append(True)

    engine = compat(lambda req: httpx.Response(200, stream=Body()))
    gen = engine.stream(system="s", messages=MESSAGES, model="m")
    assert next(gen).kind == "delta"
    gen.close()
    assert closed == [True]


def test_openai_availability_needs_key_and_models_list_is_configured():
    no_key = OpenAICompatEngine(id="openai", label="OpenAI API", kind="api",
                                base_url="https://x.test/v1", models=[{"id": "a", "label": "a"}])
    assert no_key.available() == (False, "No API key set")
    assert no_key.models() == [{"id": "a", "label": "a"}]


def local(handler) -> OpenAICompatEngine:
    """A local-server engine (no key) answering through `handler`."""
    return OpenAICompatEngine(id="ollama", label="Ollama", kind="local",
                              base_url="http://127.0.0.1:11434/v1", key_required=False,
                              live_models=True, transport=httpx.MockTransport(handler))


def test_local_engine_lists_models_live_and_is_available():
    engine = local(lambda req: httpx.Response(200, json={"data": [{"id": "llama3"}, {"id": "q"}]}))
    assert engine.available() == (True, None)
    assert [m["id"] for m in engine.models()] == ["llama3", "q"]


def test_local_engine_not_running_is_unavailable_with_reason():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    engine = local(handler)
    ok, reason = engine.available()
    assert ok is False and "not running" in reason
    assert engine.models() == []


def test_http_error_message_shapes():
    assert "no credit" in http_error_message("X", 402, "")
    assert "trouble" in http_error_message("X", 503, "<html>" + "a" * 500)
    assert len(http_error_message("X", 400, json.dumps({"error": "e" * 900}))) < 300


# ---- Anthropic ----------------------------------------------------------------------------


def anth_body(*texts_: str, extra: str = "") -> bytes:
    """A Messages-API SSE body with one text_delta per piece."""
    out = ["event: message_start\ndata: {\"type\":\"message_start\"}\n\n"]
    for t in texts_:
        data = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}
        out.append(f"event: content_block_delta\ndata: {json.dumps(data)}\n\n")
    out.append(extra)
    out.append("event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n")
    return "".join(out).encode()


def anth(handler) -> AnthropicEngine:
    """An Anthropic engine with a fake key and transport."""
    return AnthropicEngine(api_key="sk-ant-secret", transport=httpx.MockTransport(handler))


def test_anthropic_streams_text_deltas_and_sends_required_headers():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["h"], seen["body"] = dict(req.headers), json.loads(req.content)
        return split_response(anth_body("Hel", "lo"), size=9)

    events = run(anth(handler))
    assert texts(events) == "Hello" and events[-1].kind == "done"
    assert seen["h"]["x-api-key"] == "sk-ant-secret"
    assert seen["h"]["anthropic-version"] == "2023-06-01"
    assert [b["text"] for b in seen["body"]["system"]] == ["sys"] and seen["body"]["stream"] is True
    assert [m["role"] for m in seen["body"]["messages"]] == [m["role"] for m in MESSAGES]
    assert seen["body"]["messages"][-1]["content"][0]["text"] == MESSAGES[-1]["content"]


def test_anthropic_error_status_and_error_event():
    events = run(anth(lambda req: httpx.Response(429, json={"error": {"message": "slow down"}})))
    assert events[-1].kind == "error" and "rate limiting" in events[-1].text
    err = 'event: error\ndata: {"type":"error","error":{"message":"overloaded"}}\n\n'
    events = run(anth(lambda req: httpx.Response(200, content=anth_body("a", extra=err))))
    assert texts(events) == "a" and "overloaded" in events[-1].text


def test_anthropic_availability_depends_on_key():
    assert AnthropicEngine(api_key=None).available() == (False, "No API key set")
    assert AnthropicEngine(api_key="k").available() == (True, None)
    assert AnthropicEngine(api_key="k").models()[0]["id"].startswith("claude-")


def test_both_engines_cap_the_output_length_explicitly():
    """Without a limit a provider reserves the model's maximum output and may refuse the request."""
    from spyglass_service.radar.assist.engines.base import MAX_OUTPUT_TOKENS

    seen = {}

    def capture(req: httpx.Request) -> httpx.Response:
        seen[str(req.url)] = json.loads(req.content)
        return httpx.Response(200, content=sse_body(delta("x")))

    run(compat(capture))
    run(anth(capture))
    assert MAX_OUTPUT_TOKENS == 4096
    assert len(seen) == 2 and all(b["max_tokens"] == MAX_OUTPUT_TOKENS for b in seen.values())
