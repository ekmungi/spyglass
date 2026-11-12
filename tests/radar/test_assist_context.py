# ruff: noqa: F811
"""Tests for the assistant's context: system prompt, budgets, action presets."""

import pytest
from sqlmodel import Session

from spyglass_service.radar.assist import context
from spyglass_service.radar.models import RadarBrief, RadarDoc, dumps

from .test_assist_support import add_item, clean_assist_env, db  # noqa: F401


def test_system_prompt_has_role_profile_and_item(db):
    item_id = add_item(db, text="The robot cut the tissue precisely.", note="Check with Dana")
    system = context.build_system(db, item_id=item_id)
    assert "research assistant" in system and "builds with AI agents" in system
    assert "Title: Robot completes surgery" in system
    assert "Publication: Example News" in system and "https://example.org/a" in system
    assert "- First point" in system and "Relevant to endoscopy work." in system
    assert "The reader's own note on it: Check with Dana" in system
    assert "The robot cut the tissue precisely." in system


def test_system_prompt_budgets_long_text_and_handles_missing_text(db, monkeypatch):
    monkeypatch.setattr(context, "TEXT_BUDGET", 500)
    long_id = add_item(db, text="word " * 5000, url="https://example.org/long")
    assert len(context.build_system(db, item_id=long_id)) < 3_000
    bare_id = add_item(db, text=None, url="https://example.org/bare")
    assert "No full text is stored" in context.build_system(db, item_id=bare_id)
    assert "no longer exists" in context.build_system(db, item_id=99_999)


def test_system_prompt_uses_stored_profile(db):
    with Session(db) as session:
        profile = {"version": 2, "statement": "A marine biologist.", "sections": [
            {"key": "x", "label": "X", "description": ""}], "topics": [{"name": "Coral", "section": "x"}]}
        session.add(RadarDoc(key="profile", body=dumps(profile)))
        session.commit()
    system = context.build_system(db)
    assert "A marine biologist." in system and "Coral" in system


def test_system_prompt_for_a_brief_day_renders_sections(db):
    doc = {"day": "2026-11-12", "opening": "A busy day.", "sections": [
        {"key": "top", "title": "Top stories", "stories": [
            {"headline": "Big launch", "why": "Changes pricing.", "sources": [{"name": "Wire"}]}]}]}
    with Session(db) as session:
        session.add(RadarBrief(day="2026-11-12", doc=dumps(doc)))
        session.commit()
    system = context.build_system(db, brief_day="2026-11-12")
    assert "A busy day." in system and "Top stories" in system
    assert "- Big launch: Changes pricing. (Wire)" in system
    assert "No brief for that day" in context.build_system(db, brief_day="2020-01-01")


def test_build_turn_quotes_the_selection():
    turn = context.build_turn("Why?", selection="line one\nline two")
    assert turn == "The reader selected this passage:\n> line one\n> line two\n\nWhy?"
    assert context.build_turn("plain") == "plain"


@pytest.mark.parametrize("action,needle", [
    ("explain", "plain language"), ("relevance", "my stated field"),
    ("colleagues", "paste to colleagues"), ("linkedin", "no em dashes"),
    ("blog", "working title")])
def test_each_action_preset_expands_to_its_instruction(action, needle):
    assert needle in context.build_turn("", action=action)
    combined = context.build_turn("make it shorter", action=action)
    assert needle in combined and "make it shorter" in combined


def test_linkedin_preset_demands_first_person_and_link():
    text = context.ACTIONS["linkedin"]
    assert "first person" in text and "hashtags" in text and "end with the link" in text.lower()
    assert set(context.action_names()) == {"explain", "relevance", "colleagues", "linkedin", "blog", "projects",
                                           "feed_week", "feed_themes"}


def test_unknown_action_is_ignored_and_empty_turn_is_empty():
    assert context.build_turn("hi", action="bogus") == "hi"
    assert context.build_turn("", None, None) == ""


def test_trim_history_keeps_newest_within_budget_and_starts_with_user():
    msgs = [{"role": "user", "content": "a" * 100}, {"role": "assistant", "content": "b" * 100},
            {"role": "user", "content": "c" * 100}, {"role": "assistant", "content": "d" * 100},
            {"role": "user", "content": "e" * 100}]
    out = context.trim_history(msgs, budget=250)
    assert out[-1]["content"][0] == "e" and out[0]["role"] == "user"
    assert sum(len(m["content"]) for m in out) <= 250
    assert context.trim_history(msgs[-1:], budget=1) == msgs[-1:]
