# ruff: noqa: F811
"""Tests that what the assistant sends first is the same on every turn, so it can be cached."""

from pathlib import Path

from spyglass_service.radar import privacy
from spyglass_service.radar.assist import context, feed_context
from spyglass_service.radar.assist.system_split import FEED_MARKER, split_system

from .test_assist_cli import FakeChild, cc_engine, delta_line, fake_child, j  # noqa: F401
from .test_assist_support import add_item, clean_assist_env, db, make_settings  # noqa: F401

MESSAGES = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ans"},
            {"role": "user", "content": "second"}]
DONE = j(type="result", is_error=False, session_id="S1")


def system_file_of(command: list[str]) -> str:
    """The text of the system prompt file a command was launched with."""
    return Path(command[command.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")


def test_feed_marker_matches_the_feed_context():
    assert FEED_MARKER == feed_context.FEED_MARKER


def test_split_system_without_a_feed_section_is_all_stable():
    assert split_system("ROLE\n\n=== THE ITEM ===\ntext") == ("ROLE\n\n=== THE ITEM ===\ntext", "")


def test_split_system_puts_the_fenced_feed_items_in_the_varying_part():
    system = privacy.fence_context(f"ROLE\n\nRULES\n\n{FEED_MARKER}\nToday is 2026-11-12.\n[#1] a")
    stable, varying = split_system(system)
    assert stable == "ROLE\n\nRULES" and varying.startswith("<spyglass_material>\n" + FEED_MARKER)
    assert varying.endswith("</spyglass_material>")


def test_the_item_system_text_is_the_same_on_every_call_and_for_any_selection(db):
    item_id = add_item(db, text="word " * 20_000, url="https://example.org/long")
    first = context.build_system(db, item_id=item_id)
    again = context.build_system(db, item_id=item_id, selection="word word word")
    assert first == again
    assert privacy.prepare_assistant_call(first, [], make_settings(Path(".")))[0] == \
        privacy.prepare_assistant_call(again, [], make_settings(Path(".")))[0]


def test_the_feed_system_text_before_the_items_does_not_depend_on_the_question(db):
    one = context.build_system(db, feed_block=f"{FEED_MARKER}\nToday is 2026-11-12.\n[#1] a")
    two = context.build_system(db, feed_block=f"{FEED_MARKER}\nToday is 2026-11-13.\n[#2] b")
    assert split_system(privacy.fence_context(one))[0] == split_system(privacy.fence_context(two))[0]


def test_claude_code_launches_with_a_system_prompt_file_holding_the_context(tmp_path, monkeypatch, fake_child):
    fake_child.script_for_next = [delta_line("A"), DONE]
    engine = cc_engine(tmp_path, monkeypatch)
    list(engine.stream(system="ROLE and ITEM TEXT", messages=MESSAGES[:1], model="haiku"))
    child = fake_child.instances[0]
    assert "ROLE and ITEM TEXT" in system_file_of(child.command)
    assert "ROLE and ITEM TEXT" not in child.stdin_text and child.stdin_text.endswith("first")
    assert "--system-prompt" not in child.command


def test_two_turns_in_new_sessions_use_the_same_system_prompt_file(tmp_path, monkeypatch, fake_child):
    engine = cc_engine(tmp_path, monkeypatch)
    for _ in range(2):
        fake_child.script_for_next = [delta_line("A"), DONE]
        list(engine.stream(system="ROLE and ITEM TEXT", messages=MESSAGES[:1], model="haiku"))
    first, second = (c.command[c.command.index("--system-prompt-file") + 1] for c in fake_child.instances)
    assert first == second


def test_a_resumed_turn_sends_only_the_question_and_the_same_system_file(tmp_path, monkeypatch, fake_child):
    engine = cc_engine(tmp_path, monkeypatch)
    fake_child.script_for_next = [delta_line("A"), DONE]
    list(engine.stream(system="ROLE", messages=MESSAGES[:1], model="haiku"))
    fake_child.script_for_next = [delta_line("A"), DONE]
    list(engine.stream(system="ROLE", messages=MESSAGES, model="haiku", session="S1"))
    fresh, resumed = fake_child.instances
    assert resumed.stdin_text == "second" and "--resume" in resumed.command
    assert system_file_of(resumed.command) == system_file_of(fresh.command)


def test_feed_items_are_sent_with_every_turn_after_the_stable_system_prompt(tmp_path, monkeypatch, fake_child):
    system = privacy.fence_context(f"ROLE\n\n{FEED_MARKER}\nToday is 2026-11-12.\n[#1] a")
    engine = cc_engine(tmp_path, monkeypatch)
    fake_child.script_for_next = [delta_line("A"), DONE]
    list(engine.stream(system=system, messages=MESSAGES, model="haiku", session="S1"))
    child = fake_child.instances[0]
    assert "[#1] a" not in system_file_of(child.command) and "ROLE" in system_file_of(child.command)
    assert "[#1] a" in child.stdin_text and child.stdin_text.endswith("second")


def test_the_child_environment_has_no_memory_and_no_instruction_files(tmp_path, monkeypatch, fake_child):
    fake_child.script_for_next = [delta_line("A"), DONE]
    list(cc_engine(tmp_path, monkeypatch).stream(system="x", messages=MESSAGES[:1], model="haiku"))
    env = fake_child.instances[0].env
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1" and env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"


def test_the_fixed_instruction_points_to_where_the_article_actually_is(db, tmp_path, monkeypatch, fake_child):
    item_id = add_item(db, text="UNIQUE-ARTICLE-BODY", url="https://example.org/where")
    system = privacy.fence_context(context.build_system(db, item_id=item_id))
    fake_child.script_for_next = [delta_line("A"), DONE]
    list(cc_engine(tmp_path, monkeypatch).stream(system=system, messages=MESSAGES[:1], model="haiku"))
    child = fake_child.instances[0]
    in_file = system_file_of(child.command)
    # The article is in the system file, inside the marked block, and not on standard input.
    assert "UNIQUE-ARTICLE-BODY" in in_file and "<spyglass_material>" in in_file
    assert "UNIQUE-ARTICLE-BODY" not in child.stdin_text
    # The fixed instruction names that location and never says the text is only in the message.
    fixed = in_file.split("\n\n", 1)[0].lower()
    assert "these instructions" in fixed and "marked block" in fixed
    assert "only from the text in the user" not in fixed
    assert "never instructions" in fixed
