"""Tests for classifying names and refreshing the suggestions (radar/watch/suggest.py)."""

import itertools
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.models import RadarDoc, WatchEntity
from spyglass_service.radar.privacy import FENCE_TAG
from spyglass_service.radar.watch import registry, suggest

from .test_brief_seed import NOW_NAIVE, add_item, make_engine

# Settings with no model provider, so `make_llm` gives None and nothing leaves the machine.
NO_MODEL = SimpleNamespace(openrouter_api_key=None)
_SERIAL = itertools.count()


class FakeLlm:
    """A model stand-in that returns a fixed answer and records every call."""

    def __init__(self, rows: list[dict] | Exception) -> None:
        self.rows = rows
        self.calls: list[tuple[list[dict], dict]] = []

    def __call__(self, messages: list[dict], schema: dict) -> dict:
        self.calls.append((messages, schema))
        if isinstance(self.rows, Exception):
            raise self.rows
        return {"classes": self.rows}


def row(name: str, type_: str = "organisation", organisation: str = "", same_as: str = "", group: str = "") -> dict:
    """One answer row as the model writes it."""
    return {"name": name, "type": type_, "organisation": organisation, "same_as": same_as, "group": group}


@pytest.fixture
def session(tmp_path):
    """A session on a fresh radar database."""
    with Session(make_engine(tmp_path)) as s:
        yield s


def classify(session, names, llm, *, groups=(), register=()):
    """`suggest.classify` with the keyword arguments spelled once."""
    return suggest.classify(session, list(names), groups=list(groups), register=list(register), llm=llm)


def test_classify_asks_once_and_caches(session) -> None:
    llm = FakeLlm([row("Acme AI"), row("Model X", "product", organisation="Zed Labs")])
    first = classify(session, ["Acme AI", "Model X"], llm)
    assert len(llm.calls) == 1
    assert first["acme ai"]["type"] == "organisation"
    assert first["model x"] == {"type": "product", "organisation": "Zed Labs", "same_as": "", "group": ""}

    again = classify(session, ["Acme AI", "model x!"], llm)  # the second spelling normalises to the same key
    assert len(llm.calls) == 1
    assert again == first


def test_only_the_uncached_names_are_sent_and_only_they_are_stored(session) -> None:
    llm = FakeLlm([row("Acme AI")])
    classify(session, ["Acme AI"], llm)
    llm.rows = [row("Beta Corp"), row("Acme AI", "person")]  # an answer for a name that was not asked for
    result = classify(session, ["Acme AI", "Beta Corp"], llm)
    sent = llm.calls[1][0][1]["content"]  # the fenced message that carries the names
    assert "Beta Corp" in sent and "Acme AI" not in sent
    assert result["acme ai"]["type"] == "organisation"  # the cached answer was not overwritten


def test_names_reach_the_model_inside_the_privacy_fence(session) -> None:
    llm = FakeLlm([row("Acme AI")])
    classify(session, ["Acme AI"], llm)
    user = [m for m in llm.calls[0][0] if m["role"] == "user"]
    assert any(m["content"].lstrip().startswith(f"<{FENCE_TAG}>") and "Acme AI" in m["content"] for m in user)
    assert "Acme AI" not in json.dumps([m for m in llm.calls[0][0] if m["role"] == "system"])


def test_a_new_prompt_version_empties_the_cache(session, monkeypatch) -> None:
    llm = FakeLlm([row("Acme AI")])
    classify(session, ["Acme AI"], llm)
    monkeypatch.setattr(suggest, "PROMPT_VERSION", suggest.PROMPT_VERSION + 1)
    classify(session, ["Acme AI"], llm)
    assert len(llm.calls) == 2


def test_without_a_model_only_cached_names_come_back(session) -> None:
    classify(session, ["Acme AI"], FakeLlm([row("Acme AI")]))
    assert set(classify(session, ["Acme AI", "Beta Corp"], None)) == {"acme ai"}
    for failure in (LlmUnavailable("down"), ValueError("not json")):
        result = classify(session, ["Acme AI", "Beta Corp"], FakeLlm(failure))
        assert set(result) == {"acme ai"}


def test_a_reply_with_unknown_or_missing_names_is_tolerated(session) -> None:
    llm = FakeLlm([row("Acme AI"), row("Never Asked"), {"type": "organisation"}, "junk", row("Odd", "wizard")])
    result = classify(session, ["Acme AI", "Beta Corp", "Odd"], llm)
    assert set(result) == {"acme ai", "odd"}
    assert result["odd"]["type"] == "other"  # a type outside the list counts as "other"
    assert set(classify(session, ["Beta Corp"], None)) == set()  # the missing name was not cached
    assert classify(session, [], llm) == {}
    llm.rows = "not a list"
    assert classify(session, ["Gamma"], llm) == {}


def test_a_group_or_same_as_the_register_does_not_hold_is_dropped(session) -> None:
    llm = FakeLlm([
        row("Acme AI", group="Imaging", same_as="Acme Corporation"),
        row("Beta Corp", group="Made Up", same_as="Nobody"),
    ])
    result = classify(session, ["Acme AI", "Beta Corp"], llm, groups=["Imaging"], register=["Acme Corporation"])
    assert result["acme ai"]["group"] == "Imaging" and result["acme ai"]["same_as"] == "Acme Corporation"
    assert result["beta corp"]["group"] == "" and result["beta corp"]["same_as"] == ""
    assert result["beta corp"]["type"] == "organisation"  # the answer itself is kept

    # The check runs again against today's register when the answer comes from the cache.
    later = classify(session, ["Acme AI"], None, groups=["Other group"], register=[])
    assert later["acme ai"]["group"] == "" and later["acme ai"]["same_as"] == ""


def test_an_unreadable_cache_is_treated_as_empty(session) -> None:
    session.add(RadarDoc(key=suggest.CACHE_KEY, body="not json"))
    session.commit()
    llm = FakeLlm([row("Acme AI")])
    assert "acme ai" in classify(session, ["Acme AI"], llm)


# ---- refreshing the suggestions ------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    """A fresh radar database, disposed after the test."""
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


def named(engine, names: list[str], count: int, *, section: str = "health", tier: str = "top",
          age_hours: float = 3) -> list[int]:
    """Add `count` assessed items in `section` that each name every one of `names`; return their ids."""
    return [
        add_item(engine, f"{'+'.join(names)} {next(_SERIAL)}", section=section, tier=tier,
                 entities=list(names), age_hours=age_hours)
        for _ in range(count)
    ]


def add(engine, name: str, **fields) -> int:
    """Create a register entry (active unless `status` says otherwise); return its id."""
    with Session(engine) as s:
        return registry.create_entity(s, name, **fields).id


def add_suggestion(engine, name: str, *, days_old: float = 0, **fields) -> int:
    """Create a suggested entry the way the topic search or the old mention count did; return its id."""
    entity_id = add(engine, name, status="suggested", added_via="discovered", **fields)
    with Session(engine) as s:
        entity = s.get(WatchEntity, entity_id)
        entity.created_at = NOW_NAIVE - timedelta(days=days_old)
        s.add(entity)
        s.commit()
    return entity_id


def refresh(engine, llm=None, *, now=NOW_NAIVE) -> dict:
    """`suggest.refresh_suggestions` on settings without a model, at the fixed test time."""
    return suggest.refresh_suggestions(engine, NO_MODEL, now=now, llm=llm)


def suggested(engine) -> dict[str, WatchEntity]:
    """The suggested entries by name."""
    with Session(engine) as s:
        rows = s.exec(select(WatchEntity).where(WatchEntity.status == "suggested")).all()
        return {e.name: e for e in rows}


def snapshot(engine, ids: list[int]) -> dict[int, dict]:
    """The stored shape of the given entries, aliases included."""
    with Session(engine) as s:
        return {i: registry.entity_dict(s.get(WatchEntity, i)) for i in ids}


def fenced_json(llm: FakeLlm, message: int, call: int = 0):
    """The JSON that one message of one model call carried; the message must be one fenced block."""
    content = llm.calls[call][0][message]["content"]
    opening, closing = f"<{FENCE_TAG}>\n", f"\n</{FENCE_TAG}>"
    assert content.startswith(opening) and content.endswith(closing)
    return json.loads(content[len(opening):-len(closing)])


def sent_names(llm: FakeLlm, call: int = 0) -> list[str]:
    """The names one model call carried inside the privacy fence."""
    return fenced_json(llm, 1, call)


def test_five_per_section_at_least_three_items(engine) -> None:
    add(engine, "Watched Imaging Co", category="Imaging")  # gives the reader the group "Imaging"
    counts = {"Org A": 9, "Org B": 8, "Org C": 7, "Org D": 6, "Org E": 5, "Org F": 4, "Tiny Org": 2}
    for name, n in counts.items():
        named(engine, [name], n)
    named(engine, ["Skim Org"], 5, tier="skim")  # only "top" and "notable" items count
    named(engine, ["Old Org"], 5, age_hours=24 * 31)  # older than the window
    llm = FakeLlm([row("Org A", group="Imaging"), *(row(n) for n in counts if n != "Org A"),
                   row("Skim Org"), row("Old Org")])

    result = refresh(engine, llm)

    assert result == {"added": 5, "removed": 0, "kept": 0, "aliases": 0, "aliases_added": []}
    rows = suggested(engine)
    assert set(rows) == {"Org A", "Org B", "Org C", "Org D", "Org E"}
    first = rows["Org A"]
    assert (first.section, first.suggest_count, first.why) == ("health", 9, "named in 9 items")
    assert (first.added_via, first.category, first.topic) == ("discovered", "Imaging", None)
    assert (rows["Org E"].suggest_count, rows["Org E"].category) == (5, "")
    assert not {"Skim Org", "Old Org"} & set(sent_names(llm))


def test_a_busy_section_does_not_crowd_out_a_quiet_one(engine) -> None:
    busy = [f"Big Lab {i}" for i in range(7)]
    for i, name in enumerate(busy):
        named(engine, [name], 20 + i, section="models")
    named(engine, ["Quiet Medtech"], 3)
    named(engine, ["Small Device Co"], 4)
    named(engine, ["Split Co"], 3, section="health")
    named(engine, ["Split Co"], 4, section="labs")
    refresh(engine, FakeLlm([row(n) for n in [*busy, "Quiet Medtech", "Small Device Co", "Split Co"]]))

    rows = suggested(engine)
    by_section: dict[str, set[str]] = {}
    for entity in rows.values():
        by_section.setdefault(entity.section, set()).add(entity.name)
    assert by_section == {
        "models": set(busy[2:]),  # the five busiest
        "health": {"Quiet Medtech", "Small Device Co"},
        "labs": {"Split Co"},  # counted only in the section where it has the most items
    }
    assert rows["Split Co"].suggest_count == 4


def test_products_fold_into_their_organisation_and_count_each_item_once(engine) -> None:
    add(engine, "Acme")
    named(engine, ["Zed Labs"], 1)
    named(engine, ["Zed Labs", "Model X"], 1)
    named(engine, ["Model X"], 2)
    named(engine, ["Gizmo"], 3)
    named(engine, ["Research Unit"], 3)
    named(engine, ["Widget"], 5)
    llm = FakeLlm([
        row("Model X", "product", organisation="Zed Labs"),
        row("Zed Labs"),
        row("Gizmo", "product", organisation="Parent Corp"),
        row("Research Unit", organisation="Big Parent"),  # a lab of a larger company folds too
        row("Widget", "product", organisation="Acme"),  # the product of a watched name is dropped
    ])

    refresh(engine, llm)

    rows = suggested(engine)
    assert set(rows) == {"Zed Labs", "Parent Corp", "Big Parent"}
    assert (rows["Zed Labs"].suggest_count, rows["Zed Labs"].why) == (4, "named in 4 items")  # not 2 + 3
    assert rows["Parent Corp"].suggest_count == 3 and rows["Big Parent"].suggest_count == 3
    with Session(engine) as s:
        acme = s.exec(select(WatchEntity).where(WatchEntity.name == "Acme")).one()
        assert acme.aliases is None and acme.status == "active"


def test_people_products_and_publications_are_dropped(engine) -> None:
    for name in ("Jane Doe", "The Journal", "Something", "Lone Product"):
        named(engine, [name], 5)
    named(engine, ["Real Org"], 3)
    refresh(engine, FakeLlm([row("Jane Doe", "person"), row("The Journal", "publication"),
                             row("Something", "other"), row("Lone Product", "product"), row("Real Org")]))
    assert set(suggested(engine)) == {"Real Org"}


def test_a_spelling_of_a_watched_name_becomes_an_alias_and_is_not_suggested(engine) -> None:
    watched = add(engine, "Johnson & Johnson / Ethicon", category="Surgery")
    paused = add(engine, "Olympus Corporation", status="muted")
    named(engine, ["Johnson & Johnson"], 5)
    named(engine, ["Olympus"], 4)
    llm = FakeLlm([row("Johnson & Johnson", same_as="Johnson & Johnson / Ethicon"),
                   row("Olympus", same_as="Olympus Corporation")])

    result = refresh(engine, llm)

    assert result == {"added": 0, "removed": 0, "kept": 0, "aliases": 2, "aliases_added": [
        ["Johnson & Johnson", "Johnson & Johnson / Ethicon"], ["Olympus", "Olympus Corporation"]]}
    assert suggested(engine) == {}
    after = snapshot(engine, [watched, paused])
    assert after[watched]["aliases"] == ["Johnson & Johnson"] and after[watched]["status"] == "active"
    assert after[paused]["aliases"] == ["Olympus"] and after[paused]["status"] == "muted"
    register = fenced_json(llm, 2)["register"]
    assert {"Johnson & Johnson / Ethicon", "Olympus Corporation"} <= set(register)
    assert refresh(engine, llm)["aliases"] == 0  # the spelling is known now, so it is not asked again
    assert len(llm.calls) == 1


def test_a_spelling_of_a_rejected_name_is_dropped_without_an_alias(engine) -> None:
    rejected = add(engine, "Hype Corp Inc", status="rejected")
    named(engine, ["Hype Corp"], 5)
    named(engine, ["Hype Corp Inc"], 5)
    llm = FakeLlm([row("Hype Corp", same_as="Hype Corp Inc"), row("Hype Corp Inc")])

    result = refresh(engine, llm)

    assert result == {"added": 0, "removed": 0, "kept": 0, "aliases": 0, "aliases_added": []}
    assert suggested(engine) == {}
    after = snapshot(engine, [rejected])[rejected]
    assert after["status"] == "rejected" and after["aliases"] == []
    assert sent_names(llm) == ["Hype Corp"]  # the rejected name itself is never asked about
    # It is in the register the model may match against; it came from the news, so it is fenced.
    assert fenced_json(llm, 2)["register"] == ["Hype Corp Inc"]


def test_a_suggestion_no_longer_selected_is_deleted_and_followed_and_rejected_rows_are_untouched(
    engine,
) -> None:
    others = [add(engine, "Watched Co", category="Imaging"), add(engine, "Paused Co", status="muted"),
              add(engine, "Rejected Co", status="rejected")]
    for name in ("Watched Co", "Paused Co", "Rejected Co"):
        named(engine, [name], 5)
    named(engine, ["Fading Co"], 3, age_hours=24 * 29.5)
    named(engine, ["Staying Co"], 3)
    named(engine, ["Rogue Co"], 4)
    # A wrong answer: a register entry that does not exist and a group the reader does not have.
    llm = FakeLlm([row("Fading Co"), row("Staying Co"),
                   row("Rogue Co", same_as="Somebody Else", group="Made Up")])
    before = snapshot(engine, others)

    assert refresh(engine, llm)["added"] == 3
    assert suggested(engine)["Rogue Co"].category == ""
    named(engine, ["Staying Co"], 1)
    second = refresh(engine, llm, now=NOW_NAIVE + timedelta(days=1))  # Fading Co's items leave the window

    assert second == {"added": 0, "removed": 1, "kept": 2, "aliases": 0, "aliases_added": []}
    rows = suggested(engine)
    assert set(rows) == {"Staying Co", "Rogue Co"}
    assert (rows["Staying Co"].suggest_count, rows["Staying Co"].why) == (4, "named in 4 items")
    assert snapshot(engine, others) == before


def test_topic_search_names_stay_thirty_days_then_go(engine) -> None:
    young = add_suggestion(engine, "Aidoc", topic="RSNA", days_old=29)
    add_suggestion(engine, "Old Find", topic="RSNA", days_old=31)
    add_suggestion(engine, "Dr Who", topic="RSNA", days_old=1)
    add(engine, "Hype Corporation", status="rejected")
    add_suggestion(engine, "Hype Inc", topic="RSNA", days_old=2)  # another spelling of a rejected name
    named(engine, ["Aidoc"], 5)  # in the news as well: it keeps its own row, outside the sections
    llm = FakeLlm([row("Aidoc"), row("Dr Who", "person"), row("Old Find"),
                   row("Hype Inc", same_as="Hype Corporation")])

    result = refresh(engine, llm)

    assert result == {"added": 0, "removed": 3, "kept": 0, "aliases": 0, "aliases_added": []}
    rows = suggested(engine)
    assert set(rows) == {"Aidoc"} and rows["Aidoc"].id == young
    assert (rows["Aidoc"].topic, rows["Aidoc"].section, rows["Aidoc"].suggest_count) == ("RSNA", "", 0)
    assert set(sent_names(llm)) == {"Aidoc", "Dr Who", "Hype Inc"}  # the expired one is not asked about


def test_the_first_run_clears_old_mention_suggestions(engine) -> None:
    old = {name: add_suggestion(engine, name, category="Discovered", why="named in 3 relevant items")
           for name in ("Gone Co", "Some Person", "Kept Org")}
    followed = [add(engine, "Watched Co"), add(engine, "Paused Co", status="muted")]
    before = snapshot(engine, followed)
    named(engine, ["Some Person"], 6)
    named(engine, ["Kept Org"], 4)

    result = refresh(engine, FakeLlm([row("Some Person", "person"), row("Kept Org")]))

    assert result == {"added": 0, "removed": 2, "kept": 1, "aliases": 0, "aliases_added": []}
    kept = suggested(engine)
    assert set(kept) == {"Kept Org"}
    entity = kept["Kept Org"]
    assert entity.id == old["Kept Org"]
    assert (entity.category, entity.section, entity.suggest_count) == ("", "health", 4)
    assert entity.why == "named in 4 items"
    assert snapshot(engine, followed) == before


def test_without_a_model_only_cached_names_are_selected_and_the_rest_wait(engine, monkeypatch) -> None:
    named(engine, ["Cached Org"], 3)
    named(engine, ["New Org"], 5)
    add_suggestion(engine, "Stale Co", category="Discovered")
    add_suggestion(engine, "Fresh Find", topic="RSNA")
    with Session(engine) as s:
        suggest.classify(s, ["Cached Org"], groups=[], register=[], llm=FakeLlm([row("Cached Org")]))
    purposes: list[str] = []
    monkeypatch.setattr(suggest, "make_llm", lambda settings, purpose: purposes.append(purpose))

    result = refresh(engine)

    assert purposes == ["watch_suggest"]
    assert result == {"added": 1, "removed": 1, "kept": 0, "aliases": 0, "aliases_added": []}
    assert set(suggested(engine)) == {"Cached Org", "Fresh Find"}  # the uncached topic name stays too
    refresh(engine, FakeLlm([row("New Org")]))
    assert "New Org" in suggested(engine)


def test_a_click_made_while_the_model_is_asked_is_respected(engine) -> None:
    brand = add(engine, "Brand Corp")
    removed_watch = add(engine, "Removed Watch Co")
    clicked = add_suggestion(engine, "Clicked Co", category="Discovered")
    removed_find = add_suggestion(engine, "Removed Find", topic="RSNA", days_old=1)
    named(engine, ["Brand"], 4)
    named(engine, ["Racing Org"], 4)
    named(engine, ["Removed Watch"], 4)
    answer = FakeLlm([row("Brand", same_as="Brand Corp"), row("Racing Org"), row("Removed Find"),
                      row("Removed Watch", same_as="Removed Watch Co")])

    def reader_clicks_meanwhile(messages: list[dict], schema: dict) -> dict:
        """While the model answers, the reader watches a suggestion, rejects a name, adds one and removes two."""
        with Session(engine) as s:
            registry.update_entity(s, clicked, {"status": "active"})
            registry.update_entity(s, brand, {"status": "rejected"})
            registry.create_entity(s, "Racing Org")
            registry.delete_entity(s, removed_watch)
            registry.delete_entity(s, removed_find)
        return answer(messages, schema)

    result = refresh(engine, reader_clicks_meanwhile)

    assert result == {"added": 0, "removed": 0, "kept": 0, "aliases": 0, "aliases_added": []}
    after = snapshot(engine, [brand, clicked])
    assert (after[brand]["status"], after[brand]["aliases"]) == ("rejected", [])
    assert after[clicked]["status"] == "active"
    assert suggested(engine) == {}
    with Session(engine) as s:  # the removals stay removed
        assert s.get(WatchEntity, removed_watch) is None and s.get(WatchEntity, removed_find) is None
