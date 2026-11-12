"""Tests for the reader profile: validation, saving with a version bump, examples, rendering."""

import copy
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment, RadarDoc, loads
from spyglass_service.radar.profile import (
    ProfileError,
    clean_title,
    get_profile,
    profile_prompt_block,
    refresh_examples,
    save_profile,
    section_keys,
    validate_profile,
)
from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE, PROFILE_KEY

from .test_assess_support import (
    BASE_TIME,
    add_item,
    make_engine,
    set_feedback,
    set_state,
    utc,
)


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def _judge_all(engine, section: str = "agents") -> None:
    """Judge every item into a profile section: only such items may become examples."""
    with Session(engine) as session:
        for item_id in session.exec(select(Item.id)).all():
            session.add(Assessment(item_id=item_id, section=section, tier="notable", score=70))
        session.commit()


def _sending(tmp_path) -> Settings:
    """Settings with example titles switched on, never read from a .env file."""
    return Settings(_env_file=None, data_dir=tmp_path / "d", privacy_send_examples=True)


def _doc(**changes) -> dict:
    """A valid profile document with some fields replaced."""
    return {**copy.deepcopy(DEFAULT_PROFILE), **changes}


def test_get_profile_returns_an_independent_default(engine) -> None:
    """With nothing saved the default comes back, and changing it does not change the default."""
    with Session(engine) as session:
        profile = get_profile(session)
        profile["sections"].clear()
        assert get_profile(session)["sections"] == DEFAULT_PROFILE["sections"]


def test_save_profile_bumps_the_version_and_stores_the_body(engine) -> None:
    """Each save stores the document with version = previous + 1."""
    with Session(engine) as session:
        first = save_profile(session, _doc(statement="A new statement.", version=99))
        second = save_profile(session, _doc(statement="Another."))
        stored = loads(session.get(RadarDoc, PROFILE_KEY).body)
        assert (first["version"], second["version"]) == (2, 3)
        assert stored["statement"] == "Another." and stored["version"] == 3
        assert get_profile(session)["version"] == 3


@pytest.mark.parametrize(("doc", "message"), [
    ("not a dict", "JSON object"),
    (_doc(statement=""), "statement"),
    (_doc(sections=[]), "sections"),
    (_doc(sections=[{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]), "unique"),
    (_doc(sections=[{"key": "Bad Key", "label": "A"}]), "sections.0.key"),
    (_doc(topics=[{"name": "X", "section": "nowhere"}]), "unknown section"),
    (_doc(avoid=[""]), "avoid.0"),
])
def test_validate_profile_rejects_bad_shapes(doc: object, message: str) -> None:
    """Each malformed document raises ProfileError naming the problem."""
    with pytest.raises(ProfileError, match=message):
        validate_profile(doc)


def test_save_profile_stores_nothing_when_invalid(engine) -> None:
    """A rejected document leaves the stored profile alone."""
    with Session(engine) as session:
        with pytest.raises(ProfileError):
            save_profile(session, _doc(statement=""))
        assert session.get(RadarDoc, PROFILE_KEY) is None


def test_validate_profile_drops_unknown_keys_and_strips_text() -> None:
    """Unknown keys are dropped and short texts are trimmed."""
    clean = validate_profile(_doc(extra="x", avoid=["  Sports  "]))
    assert "extra" not in clean and clean["avoid"] == ["Sports"]


def test_refresh_examples_reads_every_signal_newest_first(engine, tmp_path) -> None:
    """Liked and disliked titles come from every kind of history, most recent first."""
    saved = add_item(engine, "Saved article on surgical robotics")
    set_state(engine, saved, saved_at=utc(BASE_TIME))
    more = add_item(engine, "Voted more: agent memory patterns")
    set_state(engine, more, vote="more", updated_at=utc(BASE_TIME - timedelta(days=1)))
    sent = add_item(engine, "Sent in by the reader: MCP servers", age_hours=72)
    set_state(engine, sent, from_user=True)
    thumbs = add_item(engine, "Legacy thumbs-up on FDA clearance")
    set_feedback(engine, thumbs, "up", BASE_TIME - timedelta(days=2))
    add_item(engine, "A Raindrop bookmark about colonoscopy AI", source="raindrop", age_hours=200)
    less = add_item(engine, "Voted less: celebrity gossip roundup")
    set_state(engine, less, vote="less", updated_at=utc(BASE_TIME))
    down = add_item(engine, "Legacy thumbs-down on a puzzle answer")
    set_feedback(engine, down, "down", BASE_TIME - timedelta(days=3))
    add_item(engine, "No signal at all on this one")
    _judge_all(engine)
    with Session(engine) as session:
        examples = refresh_examples(session, settings=_sending(tmp_path))
    assert examples["liked"] == [
        "Saved article on surgical robotics", "Voted more: agent memory patterns",
        "Legacy thumbs-up on FDA clearance", "Sent in by the reader: MCP servers",
        "A Raindrop bookmark about colonoscopy AI"]
    assert examples["disliked"] == [
        "Voted less: celebrity gossip roundup", "Legacy thumbs-down on a puzzle answer"]


def test_refresh_examples_caps_dedupes_and_lets_the_newest_signal_win(engine, tmp_path) -> None:
    """Short titles and repeats are skipped, the cap holds, and a later vote overrides."""
    for n in range(4):
        add_item(engine, f"Bookmark number {n} about agents", source="raindrop", age_hours=n)
    add_item(engine, "Bookmark number 0 about agents", source="raindrop", age_hours=10)
    add_item(engine, "Short", source="raindrop")
    flipped = add_item(engine, "Thumbs-up, later voted less")
    set_feedback(engine, flipped, "up", BASE_TIME - timedelta(days=5))
    set_state(engine, flipped, vote="less", updated_at=utc(BASE_TIME))
    _judge_all(engine)
    with Session(engine) as session:
        examples = refresh_examples(session, max_each=3, settings=_sending(tmp_path))
    assert examples["liked"] == ["Bookmark number 0 about agents",
                                 "Bookmark number 1 about agents",
                                 "Bookmark number 2 about agents"]
    assert examples["disliked"] == ["Thumbs-up, later voted less"]


def test_refresh_examples_rejects_a_negative_cap(engine) -> None:
    """A negative cap is a caller error."""
    with Session(engine) as session, pytest.raises(ValueError):
        refresh_examples(session, max_each=-1)


def test_clean_title_trims_suffixes_and_long_titles() -> None:
    """Site suffixes go, long titles are cut, and very short titles are dropped."""
    assert clean_title("How agents work - YouTube") == "How agents work"
    assert clean_title("Claude Code") is None and clean_title(None) is None
    long = clean_title("word " * 60)
    assert long.endswith("…") and len(long) <= 140


def test_profile_prompt_block_renders_stable_parts_before_examples() -> None:
    """Statement, sections, topics and avoid-list come first; examples last; empty is marked."""
    block = profile_prompt_block(DEFAULT_PROFILE, {"liked": ["Liked one"], "disliked": []})
    assert block.startswith("THE READER\n" + DEFAULT_PROFILE["statement"])
    assert "- health (Healthcare AI & medtech): AI in healthcare and medical imaging" in block
    assert "- AI in medical imaging [health]" in block
    assert "- Sports" in block
    assert block.index("TOPICS") < block.index("AVOID") < block.index("LIKED")
    assert block.endswith("ITEMS THE READER DISLIKED (newest first)\n- (none)")
    assert "- Liked one" in profile_prompt_block(DEFAULT_PROFILE, {"liked": ["Liked one"]})
    assert "(none)" in profile_prompt_block({"sections": []}, None)


def test_section_keys_lists_keys_in_order() -> None:
    """The keys come back in profile order; sections without a key are ignored."""
    assert section_keys(DEFAULT_PROFILE)[:2] == ["models", "labs"]
    assert section_keys({"sections": [{"label": "no key"}]}) == []
