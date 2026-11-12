"""Tests for the two-stage assessment: triage batching and recovery, digest, assess_one."""

import sys
import types

import pytest
from sqlmodel import Session, select

from spyglass_service import content_store
from spyglass_service.radar import assess
from spyglass_service.radar.assess import (
    Judge,
    LlmUnavailable,
    assess_one,
    default_llm,
    digest_one,
    item_text,
    make_judge,
    triage_rows,
)
from spyglass_service.radar.assess_prompt import triage_row
from spyglass_service.radar.models import Assessment, loads

from .test_assess_support import (
    FakeLlm,
    add_feed,
    add_item,
    make_engine,
    make_settings,
    set_state,
    store_text,
)


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database, disposed after the test."""
    eng = make_engine(tmp_path)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _no_network_fetch(monkeypatch) -> None:
    """Any fetch a test did not script fails at once instead of reaching the network."""
    def refuse(*_args, **_kwargs):
        """Stand-in for every real fetch path."""
        raise AssertionError("unscripted fetch")

    module = types.ModuleType("spyglass_service.radar.reader.build")
    module.ensure_reader_doc = refuse
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.reader.build", module)
    monkeypatch.setattr("spyglass_service.documents.fetch_fulltext", refuse)


def _judge(llm, gate: int = 50) -> Judge:
    """A Judge with a fixed profile block and the given fake model."""
    return Judge(llm=llm, block="PROFILE", keys=["models", "health"], version=3,
                 triage_model="t-model", digest_model="d-model", gate=gate)


def _rows(n: int) -> list[dict]:
    """n triage rows with ids 1..n."""
    return [triage_row(i, f"Title {i}", "Pub", "rss", "text") for i in range(1, n + 1)]


def _assessment(engine, item_id: int) -> Assessment | None:
    """The stored assessment of an item."""
    with Session(engine) as session:
        return session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()


def test_triage_rows_batches_twenty_per_call() -> None:
    """45 rows take three calls of 20, 20 and 5, and every row gets a score."""
    llm = FakeLlm(score_for=lambda i: i)
    outcome = triage_rows(_judge(llm), _rows(45))
    assert [len(call[1][-1]["content"].splitlines()) - 1 for call in llm.calls] == [20, 20, 5]
    assert len(outcome.results) == 45 and outcome.results[7].score == 7
    assert not outcome.errors and not outcome.unreachable
    assert {call[2] for call in llm.calls} == {"t-model"}


def test_triage_rows_retries_a_missing_row_alone() -> None:
    """A row left out of a batch reply is asked for again on its own, once."""
    def hook(number: int, _name: str, _messages: list[dict]):
        """First call: reply for id 1 only."""
        if number == 1:
            return {"items": [{"id": 1, "reason": "", "score": 60, "section": "", "kind": "news"}]}
        return None

    llm = FakeLlm(hook=hook)
    outcome = triage_rows(_judge(llm), _rows(2))
    assert set(outcome.results) == {1, 2} and llm.count("triage") == 2


def test_triage_rows_reports_a_row_malformed_twice() -> None:
    """A row that is malformed in the batch and again alone is reported as an error."""
    def hook(_number: int, _name: str, messages: list[dict]):
        """Always give id 2 a non-numeric score."""
        from .test_assess_support import ids_in

        return {"items": [{"id": i, "reason": "", "score": "?" if i == 2 else 70, "section": "",
                           "kind": "news"} for i in ids_in(messages)]}

    outcome = triage_rows(_judge(FakeLlm(hook=hook)), _rows(3))
    assert set(outcome.results) == {1, 3}
    assert "triage failed" in outcome.errors[2]


def test_triage_rows_retries_every_row_when_the_reply_is_not_json() -> None:
    """A batch reply that cannot be parsed sends each row through a solo retry."""
    def hook(number: int, _name: str, _messages: list[dict]):
        """The batch reply raises a JSON error; solo replies are fine."""
        if number == 1:
            raise ValueError("Expecting value: line 1 column 1")
        return None

    llm = FakeLlm(hook=hook)
    outcome = triage_rows(_judge(llm), _rows(3))
    assert set(outcome.results) == {1, 2, 3} and llm.count("triage") == 4


def test_triage_rows_leaves_items_pending_when_the_model_is_unreachable() -> None:
    """A failed batch whose first solo retry also fails is treated as an outage."""
    def hook(_number: int, _name: str, _messages: list[dict]):
        """Every call fails at the transport level."""
        raise RuntimeError("connection refused")

    llm = FakeLlm(hook=hook)
    outcome = triage_rows(_judge(llm), _rows(5))
    assert outcome.unreachable == [1, 2, 3, 4, 5] and not outcome.results
    assert llm.count("triage") == 2


def test_triage_rows_isolates_one_item_that_breaks_the_batch() -> None:
    """When only the batch call fails, solo retries judge the rows that can be judged."""
    def hook(number: int, _name: str, messages: list[dict]):
        """The batch fails; item 2 also fails alone."""
        from .test_assess_support import ids_in

        if number == 1 or ids_in(messages) == [2]:
            raise RuntimeError("HTTP 400")
        return None

    outcome = triage_rows(_judge(FakeLlm(hook=hook)), _rows(3))
    assert set(outcome.results) == {1, 3} and outcome.unreachable == [2]


def test_make_judge_uses_profile_settings_and_history(engine, tmp_path) -> None:
    """The judge carries the profile text, section keys, version, models and gate."""
    liked = add_item(engine, "A liked article about surgical robots")
    set_state(engine, liked, vote="more")
    # Only items the radar judged into a profile section may become examples (privacy bound).
    with Session(engine) as session:
        session.add(Assessment(item_id=liked, section="health", tier="notable", score=70))
        session.commit()
    judge = make_judge(engine, make_settings(tmp_path, radar_digest_gate=61), llm=FakeLlm())
    assert "A liked article about surgical robots" in judge.block
    assert judge.keys[0] == "models" and judge.version == 1
    assert (judge.triage_model, judge.digest_model, judge.gate) == ("triage-model", "digest-model", 61)


def test_default_llm_goes_through_the_seam(monkeypatch, tmp_path) -> None:
    """The real model call hands every provider's job to the seam with the pass's role and model."""
    seen = []

    def fake_seam(settings, role, messages, schema, *, model=None, runner=None):
        """Capture the seam call instead of making it."""
        seen.append((role, model, schema["name"]))
        return {"ok": True}

    monkeypatch.setattr(assess, "chat_json_for", fake_seam)
    monkeypatch.setattr(assess, "model_for", lambda _settings, _role: "triage-model")
    llm = default_llm(make_settings(tmp_path))
    assert llm([], {"name": "triage"}, "triage-model") == {"ok": True}
    assert llm([], {"name": "digest"}, "digest-model") == {"ok": True}
    assert seen == [("triage", "triage-model", "triage"), ("digest", "digest-model", "digest")]


def test_default_llm_reaches_openrouter_with_the_key_and_model(monkeypatch, tmp_path) -> None:
    """With the default provider the seam still posts to OpenRouter with the configured key."""
    from spyglass_service.radar import llm as seam

    seen = {}

    def fake_chat_json(messages, schema, *, model, api_key):
        """Capture the OpenRouter call instead of posting it."""
        seen.update(model=model, api_key=api_key, schema=schema["name"])
        return {"ok": True}

    monkeypatch.setattr(seam, "chat_json", fake_chat_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    llm = default_llm(make_settings(tmp_path))
    assert llm([{"role": "user", "content": "x"}], {"name": "triage"}, "m") == {"ok": True}
    assert seen == {"model": "m", "api_key": "test-key", "schema": "triage"}


def test_digest_one_stores_the_digest(engine, tmp_path) -> None:
    """With stored text, the digest is written with tier, lists and a slugged event key."""
    item_id = add_item(engine)
    store_text(engine, item_id, "The article body about polyp detection.")
    llm = FakeLlm()
    result = digest_one(engine, make_settings(tmp_path), _judge(llm), item_id,
                        fetch=lambda _i: pytest.fail("text was already stored"))
    assert result is not None
    row = _assessment(engine, item_id)
    assert (row.stage, row.score, row.tier, row.section, row.kind) == (
        "digest", 88, "top", "health", "regulatory")
    assert loads(row.key_points) == ["Point one with 42 cases.", "Point two.", "Point three."]
    assert loads(row.entities) == ["Olympus", "FDA"]
    assert row.event_key == "fda-clears-olympus-polyp-ai"
    assert (row.model, row.profile_version) == ("d-model", 3)
    assert "polyp detection" in llm.calls[0][1][1]["content"]


def test_digest_one_falls_back_to_the_snippet_when_no_text(engine, tmp_path) -> None:
    """When fetching stores nothing, the feed summary is judged and the model is told so."""
    item_id = add_item(engine, summary="<p>Only the feed summary.</p>")
    fetched: list[int] = []
    llm = FakeLlm()
    digest_one(engine, make_settings(tmp_path), _judge(llm), item_id, fetch=fetched.append)
    assert fetched == [item_id]
    user = llm.calls[0][1][1]["content"]
    assert "Only the feed's short summary is available" in user and "Only the feed summary." in user


def test_digest_one_keeps_triage_when_the_reply_is_unusable(engine, tmp_path) -> None:
    """Two unusable replies leave the stored triage judgement untouched."""
    item_id = add_item(engine)
    store_text(engine, item_id)
    assess.store_assessment(engine, item_id, {"stage": "triage", "score": 66, "tier": "notable"})
    llm = FakeLlm(digest={"headline": "", "score": 50})
    assert digest_one(engine, make_settings(tmp_path), _judge(llm), item_id) is None
    assert llm.count("digest") == 2
    assert _assessment(engine, item_id).stage == "triage"


def test_digest_one_returns_none_for_an_unknown_item(engine, tmp_path) -> None:
    """An id that does not exist is not digested."""
    assert digest_one(engine, make_settings(tmp_path), _judge(FakeLlm()), 999) is None


def test_digest_one_raises_when_the_model_is_unreachable(engine, tmp_path) -> None:
    """A transport failure surfaces as LlmUnavailable so the caller can retry later."""
    item_id = add_item(engine)
    store_text(engine, item_id)

    def hook(*_args):
        """Every call fails."""
        raise RuntimeError("timeout")

    with pytest.raises(LlmUnavailable):
        digest_one(engine, make_settings(tmp_path), _judge(FakeLlm(hook=hook)), item_id)


def test_assess_one_triages_only_below_the_gate(engine, tmp_path) -> None:
    """A low score stops after triage; the tier comes from the triage score."""
    item_id = add_item(engine)
    llm = FakeLlm(score_for=lambda _i: 30)
    out = assess_one(engine, make_settings(tmp_path), item_id, llm=llm)
    assert out["stage"] == "triage" and out["tier"] == "out" and llm.count("digest") == 0


def test_assess_one_digests_over_the_gate_and_skips_when_done(engine, tmp_path) -> None:
    """Over the gate the item is digested; a second call without force does nothing."""
    item_id = add_item(engine)
    store_text(engine, item_id)
    llm = FakeLlm(score_for=lambda _i: 70)
    settings = make_settings(tmp_path)
    assert assess_one(engine, settings, item_id, llm=llm)["stage"] == "digest"
    calls = len(llm.calls)
    assert assess_one(engine, settings, item_id, llm=llm)["stage"] == "digest"
    assert len(llm.calls) == calls
    assess_one(engine, settings, item_id, llm=llm, force=True)
    assert len(llm.calls) == calls + 2


def test_assess_one_digests_reader_items_and_floors_their_tier(engine, tmp_path) -> None:
    """An item the reader sent in is digested even at a low score and stays notable."""
    item_id = add_item(engine, source="raindrop")
    set_state(engine, item_id, from_user=True)
    store_text(engine, item_id)
    llm = FakeLlm(score_for=lambda _i: 10, digest={**FakeLlm().digest, "score": 20})
    out = assess_one(engine, make_settings(tmp_path), item_id, llm=llm)
    assert out["stage"] == "digest" and out["score"] == 20 and out["tier"] == "notable"


def test_assess_one_skips_items_from_disabled_feeds(engine, tmp_path) -> None:
    """A feed the reader switched off is not judged, unless the reader sent the item."""
    add_feed(engine, "https://off.example/feed", enabled=False)
    item_id = add_item(engine, feed_url="https://off.example/feed")
    llm = FakeLlm()
    out = assess_one(engine, make_settings(tmp_path), item_id, llm=llm)
    assert out == {"item_id": item_id, "skipped": "feed disabled"} and not llm.calls
    set_state(engine, item_id, from_user=True)
    out = assess_one(engine, make_settings(tmp_path), item_id, llm=llm, fetch=lambda _i: None)
    assert out["stage"] == "digest"


def test_assess_one_unknown_item_and_outage(engine, tmp_path) -> None:
    """An unknown id returns None; an unreachable model raises and stores nothing."""
    settings = make_settings(tmp_path)
    assert assess_one(engine, settings, 12345, llm=FakeLlm()) is None
    item_id = add_item(engine)

    def hook(*_args):
        """Every call fails."""
        raise RuntimeError("down")

    with pytest.raises(LlmUnavailable):
        assess_one(engine, settings, item_id, llm=FakeLlm(hook=hook))
    assert _assessment(engine, item_id) is None


def test_assess_one_records_a_triage_failure(engine, tmp_path) -> None:
    """A row malformed twice is stored as a failed triage: tier unjudged, one attempt counted,
    and the reason in `error`, never in `why` (which the reader sees)."""
    item_id = add_item(engine)
    llm = FakeLlm(hook=lambda *_a: {"items": []})
    out = assess_one(engine, make_settings(tmp_path), item_id, llm=llm)
    row = _assessment(engine, item_id)
    assert out["stage"] == "triage_failed" and out["tier"] == "unjudged"
    assert row.why is None and "triage failed" in row.error and row.triage_attempts == 1


def test_item_text_uses_stored_text_or_fetches(engine) -> None:
    """Stored text is returned as is; otherwise the fetch runs and its text is read back."""
    first = add_item(engine)
    store_text(engine, first, "stored body")
    assert item_text(engine, first, lambda _i: pytest.fail("no fetch needed")) == "stored body"
    second = add_item(engine)
    assert item_text(engine, second, lambda i: store_text(engine, i, "fresh body")) == "fresh body"

    def broken(_i: int) -> None:
        """A fetch that raises."""
        raise OSError("network")

    assert item_text(engine, add_item(engine), broken) == ""


def test_fetch_text_prefers_the_reader_package(engine, tmp_path, monkeypatch) -> None:
    """When the reader builder exists it is used and the plain fetch is not."""
    item_id = add_item(engine)
    module = types.ModuleType("spyglass_service.radar.reader.build")
    module.ensure_reader_doc = lambda eng, settings, i: store_text(eng, i, "from reader")
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.reader.build", module)
    monkeypatch.setattr("spyglass_service.documents.fetch_fulltext",
                        lambda *a, **k: pytest.fail("plain fetch must not run"))
    assess.fetch_text(engine, make_settings(tmp_path), item_id)
    assert content_store.get_fulltext(engine, item_id)["markdown"] == "from reader"


def test_fetch_text_falls_back_when_the_reader_fails(engine, tmp_path, monkeypatch) -> None:
    """A failing reader builder falls back to the engine fetch, whose result is stored."""
    item_id = add_item(engine)
    module = types.ModuleType("spyglass_service.radar.reader.build")

    def broken(*_args, **_kwargs):
        """A reader build that raises."""
        raise RuntimeError("boom")

    module.ensure_reader_doc = broken
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.reader.build", module)
    monkeypatch.setattr("spyglass_service.documents.fetch_fulltext",
                        lambda url, **_k: {"markdown": f"text of {url}", "status": "ok"})
    assess.fetch_text(engine, make_settings(tmp_path), item_id)
    assert content_store.get_fulltext(engine, item_id)["markdown"].startswith("text of https://")


def test_fetch_text_without_the_reader_package(engine, tmp_path, monkeypatch) -> None:
    """With no reader package importable, the engine fetch is used directly."""
    item_id = add_item(engine)
    monkeypatch.setitem(sys.modules, "spyglass_service.radar.reader.build", None)
    monkeypatch.setattr("spyglass_service.documents.fetch_fulltext",
                        lambda url, **_k: {"markdown": "", "status": "failed", "error": "403"})
    assess.fetch_text(engine, make_settings(tmp_path), item_id)
    stored = content_store.get_fulltext(engine, item_id)
    assert stored["status"] == "failed" and stored["error"] == "403"

