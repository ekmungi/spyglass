"""Tests for the usage table: recording, the parsers for each provider's figures, pruning."""

import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, select

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.radar import usage
from spyglass_service.radar.models import utcnow
from spyglass_service.radar.usage_parse import (
    Tokens,
    anthropic_tokens,
    claude_tokens,
    openai_tokens,
)

from .test_assist_support import make_settings


@pytest.fixture
def db(tmp_path):
    """A fresh database with every table, disposed afterwards."""
    engine = create_db_engine(tmp_path / "u.db")
    init_db(engine)
    yield engine
    engine.dispose()


def rows(engine) -> list[usage.UsageCall]:
    """Every stored usage row, oldest first."""
    with Session(engine) as session:
        return list(session.exec(select(usage.UsageCall).order_by(usage.UsageCall.id)).all())


def test_claude_tokens_reads_the_result_usage_block():
    result = {"usage": {"input_tokens": 2, "cache_creation_input_tokens": 956,
                        "cache_read_input_tokens": 3895, "output_tokens": 46},
              "total_cost_usd": 0.00025}
    tokens = claude_tokens(result)
    assert tokens == Tokens(input=2, cache_write=956, cache_read=3895, output=46, cost_usd=0.00025)
    assert tokens.context == 2 + 956 + 3895


def test_claude_tokens_is_none_without_a_usage_block():
    assert claude_tokens({}) is None
    assert claude_tokens({"usage": "oops"}) is None
    assert claude_tokens({"usage": {}}) is None


def test_openai_tokens_splits_cached_prompt_tokens_out_of_the_prompt():
    tokens = openai_tokens({"prompt_tokens": 10_339, "completion_tokens": 60,
                            "prompt_tokens_details": {"cached_tokens": 10_318,
                                                      "cache_write_tokens": 0},
                            "cost": 0.0123})
    assert (tokens.input, tokens.cache_read, tokens.cache_write, tokens.output) == (21, 10_318, 0, 60)
    assert tokens.cost_usd == 0.0123


def test_openai_tokens_without_cache_details_reports_nothing_cached_as_none():
    tokens = openai_tokens({"prompt_tokens": 100, "completion_tokens": 5})
    assert (tokens.input, tokens.cache_read, tokens.cache_write, tokens.output) == (100, None, None, 5)
    assert openai_tokens(None) is None and openai_tokens({}) is None


def test_anthropic_tokens_merges_the_start_and_delta_figures():
    start = {"input_tokens": 12, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 0,
             "output_tokens": 1}
    tokens = anthropic_tokens(start, {"output_tokens": 88})
    assert tokens == Tokens(input=12, cache_write=500, cache_read=0, output=88)
    assert anthropic_tokens(None, None) is None


def test_record_call_stores_a_row_and_returns_its_id(db):
    row_id = usage.record_call(
        db, purpose="chat", provider="claude_code", model="sonnet",
        tokens=Tokens(input=2, cache_write=100, cache_read=900, output=40, cost_usd=0.01),
        duration_ms=1200, thread_id=7, message_id=9)
    [row] = rows(db)
    assert row_id == row.id
    assert (row.purpose, row.provider, row.model) == ("chat", "claude_code", "sonnet")
    assert (row.input_tokens, row.cache_write_tokens, row.cache_read_tokens) == (2, 100, 900)
    assert (row.output_tokens, row.cost_usd, row.duration_ms) == (40, 0.01, 1200)
    assert (row.thread_id, row.message_id) == (7, 9)


def test_record_call_without_figures_stores_nulls(db):
    usage.record_call(db, purpose="triage", provider="openrouter", model="m", tokens=None)
    [row] = rows(db)
    assert row.input_tokens is None and row.cache_read_tokens is None and row.cost_usd is None


def test_record_call_swallows_a_failing_engine():
    class Boom:
        """An engine whose every use fails."""

        def connect(self, *_a, **_k):
            raise RuntimeError("down")

    assert usage.record_call(Boom(), purpose="chat", provider="p", model="m", tokens=None) is None


def test_the_table_is_created_on_a_fresh_database(db):
    assert "usagecall" in inspect(db).get_table_names()


def test_the_table_is_created_on_an_existing_database_without_it(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("create table item (id integer primary key)")
    engine = create_db_engine(path)
    try:
        assert "usagecall" not in inspect(engine).get_table_names()
        usage.record_call(engine, purpose="digest", provider="p", model="m",
                          tokens=Tokens(input=1, output=1))
        assert len(rows(engine)) == 1
    finally:
        engine.dispose()


def test_call_scope_records_into_the_settings_database_with_its_purpose(tmp_path):
    settings = make_settings(tmp_path)
    with usage.call_scope(settings, "digest"):
        usage.note_call(provider="claude_code", model="haiku",
                        tokens=Tokens(input=3, cache_write=10, cache_read=20, output=4),
                        duration_ms=50)
    engine = create_db_engine(settings.db_path)
    try:
        [row] = rows(engine)
        assert row.purpose == "digest" and row.model == "haiku" and row.cache_read_tokens == 20
    finally:
        engine.dispose()


def test_note_call_outside_a_scope_does_nothing(tmp_path):
    usage.note_call(provider="p", model="m", tokens=Tokens(input=1))  # no scope: no error, no row


def test_default_purpose_maps_the_role():
    assert usage.default_purpose("triage") == "triage"
    assert usage.default_purpose("digest") == "digest"
    assert usage.default_purpose("writer") == "other"
    assert usage.default_purpose("surprise") == "other"


def test_prune_usage_deletes_only_rows_older_than_the_limit(db):
    now = utcnow()
    with Session(db) as session:
        for age in (1, 100, 200, 400):
            session.add(usage.UsageCall(at=now - timedelta(days=age), purpose="chat",
                                        provider="p", model="m"))
        session.commit()
    assert usage.prune_usage(db, 180) == 2
    assert len(rows(db)) == 2
    assert usage.prune_usage(db, 180) == 0


def test_prune_usage_rejects_a_nonsense_limit(db):
    with pytest.raises(ValueError):
        usage.prune_usage(db, 0)


def test_a_table_from_an_earlier_version_gets_its_missing_columns(tmp_path):
    path = tmp_path / "older.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "create table usagecall (id integer primary key, at datetime, purpose varchar, "
            "provider varchar, model varchar, input_tokens integer, cache_write_tokens integer, "
            "cache_read_tokens integer, output_tokens integer, cost_usd float, duration_ms integer, "
            "thread_id integer, message_id integer)")
    engine = create_db_engine(path)
    try:
        row_id = usage.record_call(engine, purpose="chat", provider="p", model="m",
                                   tokens=Tokens(input=1, output=1, cost_usd=0.1), cost_total=0.3,
                                   condensed=True, fresh=True)
        assert row_id is not None
        [row] = rows(engine)
        assert row.cost_total == 0.3 and row.condensed is True and row.fresh is True
    finally:
        engine.dispose()
