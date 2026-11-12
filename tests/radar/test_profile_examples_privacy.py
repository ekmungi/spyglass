"""What the judging model learns about the reader is bounded and switchable."""

from datetime import timedelta

import pytest
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.radar.models import Assessment
from spyglass_service.radar.profile import (
    MAX_EXAMPLES,
    examples_switch,
    profile_prompt_block,
    refresh_examples,
)
from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE

from .test_assess_support import BASE_TIME, add_item, make_engine, set_state, utc


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


def _settings(tmp_path, send: bool) -> Settings:
    """Settings with the example switch set, never read from a .env file."""
    return Settings(_env_file=None, data_dir=tmp_path / "d", privacy_send_examples=send)


def judge(engine, item_id: int, section: str, tier: str) -> None:
    """Record the radar's judgement of an item."""
    with Session(engine) as session:
        session.add(Assessment(item_id=item_id, section=section, tier=tier, score=70))
        session.commit()


def _liked(engine, title: str, section: str | None, tier: str = "notable", age: int = 0) -> int:
    """A saved item, judged into `section` (or not judged at all when None)."""
    item_id = add_item(engine, title)
    set_state(engine, item_id, saved_at=utc(BASE_TIME - timedelta(hours=age)))
    if section is not None:
        judge(engine, item_id, section, tier)
    return item_id


def test_with_the_switch_off_no_title_is_sent(engine, tmp_path) -> None:
    """Off means empty lists, and the prompt block shows none."""
    _liked(engine, "Saved article on surgical robotics", "health")
    with Session(engine) as session:
        examples = refresh_examples(session, settings=_settings(tmp_path, False))
    assert examples == {"liked": [], "disliked": []}
    block = profile_prompt_block(DEFAULT_PROFILE, examples)
    assert "surgical robotics" not in block


def test_only_items_judged_into_a_section_become_examples(engine, tmp_path) -> None:
    """Personal bookmarks (no section, out, unjudged, or a section the profile lacks) never do."""
    _liked(engine, "Saved article on surgical robotics", "health", age=1)
    _liked(engine, "My mortgage refinancing checklist notes", "", tier="out", age=2)
    _liked(engine, "Family doctor appointment reminder page", "health", tier="out", age=3)
    _liked(engine, "Bookmark never judged by the radar at all", None, age=4)
    _liked(engine, "Judged into a section the profile lacks", "finance", age=5)
    less = add_item(engine, "Voted less: routine benchmark preprint")
    set_state(engine, less, vote="less", updated_at=utc(BASE_TIME))
    judge(engine, less, "models", "skim")
    with Session(engine) as session:
        examples = refresh_examples(session, settings=_settings(tmp_path, True))
    assert examples == {"liked": ["Saved article on surgical robotics"],
                        "disliked": ["Voted less: routine benchmark preprint"]}


def test_examples_are_capped_at_25_each(engine, tmp_path) -> None:
    """A larger requested cap is reduced to the bound."""
    for n in range(MAX_EXAMPLES + 5):
        _liked(engine, f"Saved article number {n:02d} on agents", "agents", age=n)
    with Session(engine) as session:
        examples = refresh_examples(session, max_each=100, settings=_settings(tmp_path, True))
    assert len(examples["liked"]) == MAX_EXAMPLES == 25


def test_examples_switch_reads_the_given_settings(tmp_path) -> None:
    """The switch follows the settings it is given."""
    assert examples_switch(_settings(tmp_path, True)) is True
    assert examples_switch(_settings(tmp_path, False)) is False


def test_examples_switch_fails_closed_when_settings_cannot_load(monkeypatch) -> None:
    """With no settings and a broken configuration, nothing is sent."""
    import spyglass_service.config as config

    def broken(*args, **kwargs):
        raise ValueError("bad configuration")

    monkeypatch.setattr(config, "Settings", broken)
    assert examples_switch(None) is False
