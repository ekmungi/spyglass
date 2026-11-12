"""Tests for discovering watch entities with a model and verifying them against news."""

from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.radar.models import WatchEntity
from spyglass_service.radar.watch import registry
from spyglass_service.radar.watch.discover import discover, discover_detailed, make_verifier

from .test_brief_seed import make_engine


def org(name: str, category: str = "Endoscopy AI", **kw) -> dict:
    """One organisation as the model returns it."""
    return {"name": name, "kind": "company", "category": category, "aliases": [], "why": "matters",
            "query": f'"{name}"', **kw}


def fake_llm(orgs: list[dict]):
    """An llm callable returning the given organisations."""
    return lambda messages, schema: {"organisations": orgs}


def hit(title: str) -> CollectedItem:
    """A news result."""
    return CollectedItem(source="news", external_id=title, title=title, url="https://n.example/x")


def test_invented_names_are_rejected_by_verification(tmp_path) -> None:
    engine = make_engine(tmp_path)
    real = {"Medtronic": "Medtronic recalls device", "Olympus": "Olympus launches scope"}

    def verify(entity: dict) -> bool:
        return entity["name"] in real

    res = discover_detailed(engine, None, "endoscopy AI", llm=fake_llm(
        [org("Medtronic"), org("Zorbotix Quantum Gut"), org("Olympus")]), verify=verify)
    assert [e["name"] for e in res.accepted] == ["Medtronic", "Olympus"]
    assert res.rejected == ["Zorbotix Quantum Gut"]
    with Session(engine) as s:
        names = {e.name: e for e in s.exec(select(WatchEntity)).all()}
    assert set(names) == {"Medtronic", "Olympus"}
    assert names["Medtronic"].status == "suggested" and names["Medtronic"].added_via == "discovered"
    assert names["Medtronic"].topic == "endoscopy AI" and names["Medtronic"].category == "Endoscopy AI"
    engine.dispose()


def test_activate_stores_active_entities(tmp_path) -> None:
    engine = make_engine(tmp_path)
    out = discover(engine, None, "t", llm=fake_llm([org("Alpha")]), verify=lambda e: True, activate=True)
    assert out[0]["status"] == "active"
    engine.dispose()


def test_existing_and_duplicate_names_are_skipped_not_reverified(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        registry.create_entity(s, "Alpha", aliases=["Alp"])
    checked = []
    res = discover_detailed(
        engine, None, "t",
        llm=fake_llm([org("alpha"), org("Alp"), org("Beta"), org("beta!")]),
        verify=lambda e: checked.append(e["name"]) or True,
    )
    assert checked == ["Beta"]
    assert [e["name"] for e in res.accepted] == ["Beta"]
    assert sorted(res.existing) == ["Alp", "alpha"]
    engine.dispose()


def test_malformed_proposals_are_ignored_and_kind_is_normalised(tmp_path) -> None:
    engine = make_engine(tmp_path)
    res = discover_detailed(
        engine, None, "t",
        llm=fake_llm([{"name": ""}, "junk", org("Gamma", kind="spaceship", category="")]),  # type: ignore[list-item]
        verify=lambda e: True,
    )
    assert [(e["name"], e["kind"], e["category"]) for e in res.accepted] == [("Gamma", "company", "Other")]
    engine.dispose()


def test_no_model_configured_raises(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with pytest.raises(RuntimeError):
        discover(engine, SimpleNamespace(openrouter_api_key=None), "t", verify=lambda e: True)
    engine.dispose()


def test_default_verifier_needs_a_result_that_names_the_entity() -> None:
    sleeps = []
    calls = []

    def search(query: str, days: int = 0):
        calls.append((query, days))
        if "Real" in query:
            return [hit("Unrelated headline"), hit("Real Co announces a new product")]
        if "Alias" in query:
            return [hit("The Old Name Inc. expands")]
        if "Boom" in query:
            raise RuntimeError("network")
        return [hit("Nothing about it")]

    verify = make_verifier(search, sleep=sleeps.append, pause=1.0)
    assert verify({"name": "Real Co", "query": '"Real Co"'}) is True
    assert verify({"name": "Alias Co", "query": '"Alias"', "aliases": ["Old Name"]}) is True
    assert verify({"name": "Ghost Corp", "query": '"Ghost"'}) is False
    assert verify({"name": "Boom", "query": '"Boom"'}) is False
    assert calls[0][1] == 120 and len(sleeps) == 3  # throttled after the first search


def test_verifier_matches_whole_phrases_only() -> None:
    verify = make_verifier(lambda q, days=0: [hit("Microsoftware sales rise")], sleep=lambda s: None)
    assert verify({"name": "Microsoft", "query": "x"}) is False


def test_name_forms_drop_corporate_endings_and_brackets() -> None:
    from spyglass_service.radar.watch.discover import core_name, name_forms

    assert core_name("Olympus Corporation") == "Olympus"
    assert core_name("Medtronic (GI Genius)") == "Medtronic"
    assert core_name("Fujifilm Medical Systems") == "Fujifilm"
    assert core_name("Systems") == "Systems"
    forms = name_forms({"name": "Olympus Corporation", "aliases": ["Evident"]})
    assert forms == ["Olympus Corporation", "Olympus", "Evident"]


def test_verifier_retries_with_the_plain_name_when_the_model_query_finds_nothing() -> None:
    queries = []

    def search(query: str, days: int = 0):
        queries.append(query)
        return [hit("Olympus recalls scope")] if query == '"Olympus"' else []

    verify = make_verifier(search, sleep=lambda s: None)
    entity = {"name": "Olympus Corporation", "query": '"Olympus ENDO-AID" gastro', "aliases": []}
    assert verify(entity) is True
    assert queries == ['"Olympus ENDO-AID" gastro', '"Olympus"']


def test_same_organisation_under_another_spelling_counts_as_existing(tmp_path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as s:
        registry.create_entity(s, "US Food and Drug Administration (FDA)")
    res = discover_detailed(
        engine, None, "t",
        llm=fake_llm([org("FDA (Center for Devices and Radiological Health)"), org("Medtronic (GI Genius)"),
                      org("Medtronic (Robotics)")]),
        verify=lambda e: True,
    )
    assert [e["name"] for e in res.accepted] == ["Medtronic (GI Genius)"]
    assert res.existing == ["FDA (Center for Devices and Radiological Health)", "Medtronic (Robotics)"]
    engine.dispose()
