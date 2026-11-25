"""Tests for classifying names with one cached model call (radar/watch/suggest.py)."""

import json

import pytest
from sqlmodel import Session

from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.models import RadarDoc
from spyglass_service.radar.privacy import FENCE_TAG
from spyglass_service.radar.watch import suggest

from .test_brief_seed import make_engine


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
