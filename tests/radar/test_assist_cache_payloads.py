"""Tests that the API engines mark what stays the same for the provider's prompt cache."""

import json

import httpx

from spyglass_service.radar import privacy
from spyglass_service.radar.assist.engines.anthropic_api import AnthropicEngine
from spyglass_service.radar.assist.engines.cache_blocks import mark_last_message, system_blocks
from spyglass_service.radar.assist.engines.openai_compat import OpenAICompatEngine
from spyglass_service.radar.assist.system_split import FEED_MARKER

from .test_assist_support import delta, sse_body

EPHEMERAL = {"type": "ephemeral"}
MESSAGES = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ans"},
            {"role": "user", "content": "second"}]
ANTHROPIC_DONE = "".join([
    "event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta", "delta": {
        "type": "text_delta", "text": "Hi"}}) + "\n\n",
    "event: message_stop\ndata: " + json.dumps({"type": "message_stop"}) + "\n\n"]).encode()


def test_system_blocks_marks_the_whole_stable_prompt_and_leaves_nothing_else_marked():
    assert system_blocks("ROLE and ITEM") == [
        {"type": "text", "text": "ROLE and ITEM", "cache_control": EPHEMERAL}]


def test_system_blocks_keeps_the_retrieved_feed_items_after_the_marked_block():
    system = privacy.fence_context(f"ROLE\n\n{FEED_MARKER}\n[#1] a")
    blocks = system_blocks(system)
    assert blocks[0] == {"type": "text", "text": "ROLE", "cache_control": EPHEMERAL}
    assert blocks[1]["text"].startswith("<spyglass_material>") and "cache_control" not in blocks[1]


def test_mark_last_message_changes_only_the_last_message_and_not_the_input():
    marked = mark_last_message(MESSAGES)
    assert marked[0] == MESSAGES[0] and marked[1] == MESSAGES[1]
    assert marked[2] == {"role": "user", "content": [
        {"type": "text", "text": "second", "cache_control": EPHEMERAL}]}
    assert MESSAGES[2]["content"] == "second"


def test_mark_last_message_leaves_an_empty_message_and_an_empty_list_alone():
    assert mark_last_message([]) == []
    assert mark_last_message([{"role": "user", "content": ""}]) == [{"role": "user", "content": ""}]


def test_anthropic_request_has_a_cache_breakpoint_on_the_system_block_and_the_last_message():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, content=ANTHROPIC_DONE,
                              headers={"content-type": "text/event-stream"})

    engine = AnthropicEngine(api_key="sk-test-key-123456", transport=httpx.MockTransport(handler))
    list(engine.stream(system="ROLE and ITEM", messages=MESSAGES, model="claude-sonnet-5-5"))
    payload = seen["payload"]
    assert payload["system"] == [{"type": "text", "text": "ROLE and ITEM", "cache_control": EPHEMERAL}]
    assert payload["messages"][:2] == MESSAGES[:2]
    assert payload["messages"][2]["content"] == [
        {"type": "text", "text": "second", "cache_control": EPHEMERAL}]


def openrouter_payload(engine_id: str, model: str) -> dict:
    """The JSON an OpenAI-compatible engine with this id sends for `model`."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, content=sse_body(delta("Hi")),
                              headers={"content-type": "text/event-stream"})

    engine = OpenAICompatEngine(id=engine_id, label="X", kind="api", base_url="https://example.org/v1",
                                key_required=False, models=[], transport=httpx.MockTransport(handler))
    list(engine.stream(system="ROLE and ITEM", messages=MESSAGES, model=model))
    return seen["payload"]


def test_openrouter_anthropic_models_get_cache_control_in_openrouters_format():
    payload = openrouter_payload("openrouter", "anthropic/claude-sonnet-5.5")
    assert payload["messages"][0] == {"role": "system", "content": [
        {"type": "text", "text": "ROLE and ITEM", "cache_control": EPHEMERAL}]}
    assert payload["messages"][-1]["content"] == [
        {"type": "text", "text": "second", "cache_control": EPHEMERAL}]


def test_openrouter_other_models_are_sent_plain_text_because_they_cache_by_themselves():
    for model in ("openai/gpt-6.1-sol", "google/gemini-3.8-flash", "deepseek/deepseek-v4.1-flash"):
        payload = openrouter_payload("openrouter", model)
        assert payload["messages"][0] == {"role": "system", "content": "ROLE and ITEM"}
        assert payload["messages"][-1]["content"] == "second"


def test_other_services_get_plain_text_even_for_a_model_with_an_anthropic_name():
    payload = openrouter_payload("openai", "anthropic/claude-sonnet-5.5")
    assert payload["messages"][0] == {"role": "system", "content": "ROLE and ITEM"}
