"""Tests for the name classification's chunks, prompt and cache freshness (radar/watch/suggest.py).

The model is asked about at most `suggest.CHUNK` names per call, so a failed call loses only its
own names; two spellings of one organisation fold into one suggestion; a cached answer is asked
again when the register or the groups it was given have changed in a way that matters; and every
alias a refresh adds to a followed entry is logged and reported.
"""

import json
import logging

import pytest
from sqlmodel import Session

from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.privacy import FENCE_TAG
from spyglass_service.radar.watch import groups, registry, suggest

from .test_brief_seed import make_engine
from .test_watch_suggest import FakeLlm, add, named, refresh, row, sent_names, suggested


@pytest.fixture
def engine(tmp_path):
    """A fresh radar database, disposed after the test."""
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


class ChunkLlm:
    """A model stand-in that answers "organisation" for every name it is sent, failing on chosen calls."""

    def __init__(self, fail_on: set[int] | None = None, failure: Exception | None = None) -> None:
        self.fail_on = fail_on or set()
        self.failure = failure or TimeoutError("the call took too long")
        self.sent: list[list[str]] = []

    def __call__(self, messages: list[dict], schema: dict) -> dict:
        content = messages[1]["content"]
        names = json.loads(content[len(f"<{FENCE_TAG}>\n"):-len(f"\n</{FENCE_TAG}>")])
        self.sent.append(names)
        if len(self.sent) in self.fail_on:
            raise self.failure
        return {"classes": [row(name) for name in names]}


def test_names_are_asked_in_chunks_and_a_failed_chunk_loses_only_its_own(engine) -> None:
    names = [f"Org {i:02d}" for i in range(70)]
    llm = ChunkLlm(fail_on={2}, failure=LlmUnavailable("OpenRouter could not be reached: timed out"))
    with Session(engine) as s:
        first = suggest.classify(s, names, groups=[], register=[], llm=llm)
    assert [len(chunk) for chunk in llm.sent] == [30, 30, 10]
    assert set(first) == {registry.norm_name(n) for n in names[:30] + names[60:]}

    again = ChunkLlm()
    with Session(engine) as s:
        second = suggest.classify(s, names, groups=[], register=[], llm=again)
    assert again.sent == [names[30:60]]  # only the failed chunk is asked again
    assert len(second) == 70


@pytest.mark.parametrize("failure", [KeyError("choices"), TypeError("the JSON object must be str, not NoneType")])
def test_a_malformed_reply_fails_its_chunk_and_never_the_stage(engine, failure) -> None:
    named(engine, ["Acme AI"], 4)
    result = refresh(engine, FakeLlm(failure))
    assert result["added"] == 0
    assert suggested(engine) == {}
    refresh(engine, FakeLlm([row("Acme AI")]))  # the name was not cached, so the next cycle asks again
    assert set(suggested(engine)) == {"Acme AI"}


def test_two_spellings_answered_with_one_organisation_are_one_suggestion(engine) -> None:
    full = "Department of Health and Human Services"
    named(engine, ["HHS", full], 2)
    named(engine, ["HHS"], 1)
    named(engine, [full], 1)
    llm = FakeLlm([row("HHS", organisation=full), row(full)])

    refresh(engine, llm)

    rows = suggested(engine)
    assert set(rows) == {full}
    assert rows[full].suggest_count == 4  # an item that names both counts once
    prompt = llm.calls[0][0][0]["content"]
    assert "short form" in prompt and "watches" not in prompt


def test_a_spelling_cached_before_its_organisation_was_rejected_is_asked_again(engine) -> None:
    named(engine, ["Hype Corp"], 5)
    named(engine, ["Hype Corporation"], 4)
    refresh(engine, FakeLlm([row("Hype Corp"), row("Hype Corporation")]))
    assert {"Hype Corp", "Hype Corporation"} <= set(suggested(engine))
    with Session(engine) as s:
        registry.update_entity(s, suggested(engine)["Hype Corporation"].id, {"status": "rejected"})

    llm = FakeLlm([row("Hype Corp", same_as="Hype Corporation")])
    refresh(engine, llm)

    assert sent_names(llm) == ["Hype Corp"]
    assert "Hype Corp" not in suggested(engine)
    llm.rows = []
    refresh(engine, llm)  # the register has not changed since, so the answer is not asked for again
    assert len(llm.calls) == 1


def test_names_cached_with_a_renamed_group_are_asked_again_and_keep_a_category(engine) -> None:
    add(engine, "Watched Imaging Co", category="Imaging")
    named(engine, ["Org A"], 5)
    named(engine, ["Org B"], 4)
    refresh(engine, FakeLlm([row("Org A", group="Imaging"), row("Org B")]))
    assert suggested(engine)["Org A"].category == "Imaging"
    with Session(engine) as s:
        groups.apply_group_action(s, "Imaging", "rename", to="Medical imaging")

    llm = FakeLlm([row("Org A", group="Medical imaging")])
    refresh(engine, llm)

    assert sent_names(llm) == ["Org A"]  # Org B had no group, so its answer still holds
    assert suggested(engine)["Org A"].category == "Medical imaging"


def test_every_alias_a_refresh_adds_is_logged_and_reported(engine, caplog) -> None:
    """A wrong `same_as` that names a real entry still adds an alias, so the reader can see it in the log."""
    add(engine, "DeepMind (Alphabet/Google)", category="AI labs")
    named(engine, ["Google"], 4)

    with caplog.at_level(logging.INFO, logger=suggest.__name__):
        result = refresh(engine, FakeLlm([row("Google", same_as="DeepMind (Alphabet/Google)")]))

    assert result["aliases"] == 1
    assert result["aliases_added"] == [["Google", "DeepMind (Alphabet/Google)"]]
    logged = [r for r in caplog.records if r.levelno == logging.INFO and "alias" in r.getMessage()]
    assert len(logged) == 1
    assert "Google" in logged[0].getMessage() and "DeepMind (Alphabet/Google)" in logged[0].getMessage()
