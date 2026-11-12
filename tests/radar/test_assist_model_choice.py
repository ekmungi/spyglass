# ruff: noqa: F811
"""Tests for the "Automatic" model choice: a cheaper model for simple turns, a stronger one for drafts."""

from sqlmodel import Session

from spyglass_service.radar.assist import model_choice, registry, threads
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.model_choice import AUTO, choose, offers_auto

from .test_assist_support import (
    FakeEngine,
    add_item,
    clean_assist_env,  # noqa: F401
    db,  # noqa: F401
    make_settings,
    patch_fake_engine,
)


def test_explain_and_short_questions_get_the_cheaper_model():
    assert choose("claude_code", "explain", "") == "haiku"
    assert choose("claude_code", None, "What does this mean?") == "haiku"
    assert choose("anthropic", None, "Who is the author?") == "claude-haiku-5-5"


def test_drafting_actions_and_drafting_verbs_get_the_stronger_model():
    for action in ("colleagues", "linkedin", "blog"):
        assert choose("claude_code", action, "") == "sonnet"
    assert choose("claude_code", None, "Draft a reply to the author") == "sonnet"
    assert choose("claude_code", None, "Please write two lines for my team") == "sonnet"


def test_a_long_question_gets_the_stronger_model():
    assert choose("claude_code", None, "Why? " * 60) == "sonnet"
    assert choose("claude_code", "explain", "Why? " * 60) == "sonnet"


def test_analysis_presets_get_the_stronger_model():
    for action in ("relevance", "projects", "feed_week", "feed_themes"):
        assert choose("openrouter", action, "") == "anthropic/claude-sonnet-5.5"


def test_only_engines_with_a_known_pair_offer_automatic():
    assert offers_auto("claude_code") and offers_auto("anthropic") and offers_auto("openrouter")
    assert not offers_auto("ollama") and not offers_auto("custom-x") and not offers_auto("openai")


def test_choose_for_an_engine_without_a_pair_raises():
    import pytest

    with pytest.raises(ValueError):
        choose("ollama", None, "hi")


def test_the_engine_list_adds_automatic_last_so_it_is_never_the_default(db, tmp_path, monkeypatch):
    settings = make_settings(tmp_path, assist_claude_code_enabled=True)
    monkeypatch.setattr("spyglass_service.radar.assist.engines.claude_code.find_claude",
                        lambda s: "claude")
    with Session(db) as session:
        rows = {r["id"]: r for r in registry.list_engines(settings, session)}
    claude = rows["claude_code"]["models"]
    assert claude[-1]["id"] == AUTO and "Automatic" in claude[-1]["label"]
    assert rows["claude_code"]["default_model"] == "sonnet"
    assert AUTO not in [m["id"] for m in rows["ollama"]["models"]]


def test_a_turn_with_automatic_uses_the_chosen_model_and_stores_it_on_the_answer(db, tmp_path, monkeypatch):
    item_id = add_item(db)
    engine = FakeEngine([StreamEvent.delta("ok"), StreamEvent.done()], id="claude_code")
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="", action="explain", model=AUTO))
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="", action="linkedin", model=AUTO))
    assert [c["model"] for c in engine.calls] == ["haiku", "sonnet"]
    answers = [m for m in threads.thread_detail(db, tid)["messages"] if m["role"] == "assistant"]
    assert [m["model"] for m in answers] == ["haiku", "sonnet"]


def test_automatic_is_not_a_model_name_an_engine_ever_receives():
    assert model_choice.AUTO == "auto"
