"""Tests that the judging and writing calls record their token use under the right purpose."""

import json

import httpx
import pytest
from sqlmodel import Session, select

from spyglass_service import openrouter
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine
from spyglass_service.radar import llm_openai_compat, usage
from spyglass_service.radar.llm import chat_json_for
from spyglass_service.radar.llm_claude import RunResult, claude_chat_json

SCHEMA = {"name": "t", "strict": True, "schema": {
    "type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
    "additionalProperties": False}}
MESSAGES = [{"role": "system", "content": "Be strict."}, {"role": "user", "content": "Go."}]
CLAUDE_RESULT = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.002,
                 "structured_output": {"a": "x"},
                 "usage": {"input_tokens": 3, "cache_creation_input_tokens": 50,
                           "cache_read_input_tokens": 400, "output_tokens": 9}}


def runner(command, prompt, cwd, timeout_s) -> RunResult:
    """A fake `claude` process that answers with CLAUDE_RESULT."""
    return RunResult(0, json.dumps(CLAUDE_RESULT), "")


def settings(tmp_path, **extra) -> Settings:
    """Settings that keep their data in tmp_path and use the Claude command."""
    return Settings(_env_file=None, data_dir=tmp_path, claude_command="claude",
                    radar_llm_provider="claude_code", **extra)


def stored(cfg: Settings) -> list[usage.UsageCall]:
    """The usage rows in the settings' database."""
    engine = create_db_engine(cfg.db_path)
    try:
        with Session(engine) as session:
            return list(session.exec(select(usage.UsageCall).order_by(usage.UsageCall.id)).all())
    finally:
        engine.dispose()


def test_claude_call_in_a_scope_records_tokens_model_and_purpose(tmp_path):
    cfg = settings(tmp_path)
    with usage.call_scope(cfg, "triage"):
        claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=cfg, runner=runner)
    [row] = stored(cfg)
    assert (row.purpose, row.provider, row.model) == ("triage", "claude_code", "haiku")
    assert (row.input_tokens, row.cache_write_tokens, row.cache_read_tokens, row.output_tokens) == (
        3, 50, 400, 9)
    assert row.cost_usd == 0.002 and row.duration_ms is not None


def test_claude_call_outside_a_scope_records_nothing(tmp_path):
    cfg = settings(tmp_path)
    claude_chat_json(MESSAGES, SCHEMA, model="haiku", settings=cfg, runner=runner)
    assert not cfg.db_path.exists()


def test_the_seam_names_the_purpose_from_the_role_or_the_caller(tmp_path):
    cfg = settings(tmp_path)
    chat_json_for(cfg, "triage", MESSAGES, SCHEMA, runner=runner)
    chat_json_for(cfg, "digest", MESSAGES, SCHEMA, runner=runner)
    chat_json_for(cfg, "writer", MESSAGES, SCHEMA, runner=runner)
    chat_json_for(cfg, "writer", MESSAGES, SCHEMA, runner=runner, purpose="brief_opening")
    assert [r.purpose for r in stored(cfg)] == ["triage", "digest", "other", "brief_opening"]


def test_a_failing_call_records_nothing_and_still_raises(tmp_path):
    cfg = settings(tmp_path)

    def failing(command, prompt, cwd, timeout_s) -> RunResult:
        return RunResult(1, json.dumps({"type": "result", "is_error": True, "result": "boom"}), "")

    with pytest.raises(Exception, match="Claude Code failed"):
        chat_json_for(cfg, "digest", MESSAGES, SCHEMA, runner=failing)
    assert not cfg.db_path.exists()


def test_openrouter_call_records_cached_tokens(tmp_path):
    cfg = Settings(_env_file=None, data_dir=tmp_path)
    body = {"choices": [{"message": {"content": json.dumps({"a": "x"})}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 20, "cost": 0.004,
                      "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 0}}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with usage.call_scope(cfg, "digest"):
        out = openrouter.chat_json(MESSAGES, SCHEMA, model="m", api_key="sk-or-test-123456",
                                   transport=transport, settings=cfg)
    assert out == {"a": "x"}
    [row] = stored(cfg)
    assert (row.provider, row.model, row.input_tokens, row.cache_read_tokens, row.output_tokens) == (
        "openrouter", "m", 100, 900, 20)
    assert row.cost_usd == 0.004


def test_gemini_call_records_tokens(tmp_path):
    cfg = Settings(_env_file=None, data_dir=tmp_path)
    body = {"choices": [{"message": {"content": json.dumps({"a": "x"})}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with usage.call_scope(cfg, "other"):
        llm_openai_compat.chat_json(
            MESSAGES, SCHEMA, base_url=llm_openai_compat.GEMINI_BASE_URL, api_key="gem-test-123456",
            model="gemini-x", label="Gemini", allowed_hosts=llm_openai_compat.GEMINI_HOSTS,
            transport=transport)
    [row] = stored(cfg)
    assert (row.provider, row.model, row.input_tokens, row.output_tokens) == ("gemini", "gemini-x", 50, 5)
