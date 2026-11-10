# tests/test_enrich.py
"""Tests for the relevance-gated enrichment cascade.

Covers all four cascade branches:
  1. Gate 1 reject   -- cheap blurb scores low -> no fetch, judgment persisted.
  2. Relevant path   -- Gate 1 passes -> fetch -> Gate 2 -> summary + embed.
  3. Hypothesis break -- Gate 1 passes, Gate 2 drops score below gate -> not recommended.
  4. Fetch failure   -- Gate 1 passes, fetch returns non-ok -> degrade gracefully.
  5. Pending skip    -- enrich_pending skips already-judged cards (relevance caching).
"""
from datetime import UTC, datetime

from spyglass_service.enrich import enrich_item, enrich_pending, run_scheduled_enrich
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Card, RunLog
from sqlmodel import Session
import numpy as np


def _index():
    """Tiny 4-dim fake EmbeddingIndex; avoids any real model download."""
    return EmbeddingIndex(lambda t: np.ones((len(t), 4), dtype=np.float32), "fake", 4)


def _llm(seq):
    """Return successive canned JSON dicts per call."""
    calls = iter(seq)
    return lambda messages: next(calls)


def _settings(tmp_path):
    from spyglass_service.config import Settings
    # openrouter_api_key uses AliasChoices and cannot be passed by field name;
    # all tests inject llm directly so the default LLM (which uses the key) is never called.
    return Settings(_env_file=None, data_dir=tmp_path, relevance_gate=40)


def test_gate1_reject_skips_fetch(engine_with_card, tmp_path):  # card id=1, item url set
    fetched = {"n": 0}
    def fetcher(url):
        fetched["n"] += 1
        return {"markdown": "x", "status": "ok", "content_type": "", "source_url": url}
    llm = _llm([{"relevance_score": 5, "relevance_reason": "no", "summary": "", "tags": [], "fits": False, "confidence": 0.9}])
    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)
    assert out["recommended"] is False and fetched["n"] == 0
    with Session(engine_with_card) as s:
        card = s.get(Card, 1)
    assert card.relevance_score == 5 and card.relevance_at is not None  # judged + cached
    assert card.summary == ""  # not summarized


def test_bypass_gate_fetches_even_when_gate1_scores_low(engine_with_card, tmp_path):
    """An explicit user fetch (bypass_gate=True) fetches + summarizes even below the gate.

    bypass_gate skips Gate-1 ENTIRELY -- the sole LLM call is Gate-2 on the full text.
    A low relevance score is irrelevant; the user asked for the text, so we fetch and summarize.
    """
    from spyglass_service.content_store import get_fulltext

    def fetcher(url):
        return {"markdown": "full body text", "status": "ok", "content_type": "", "source_url": url}

    # The sole LLM call -- Gate-2 on the full text (Gate-1 is skipped). Score is below the gate
    # of 40, but the summary is still produced because the fetch was explicit.
    llm = _llm([
        {"relevance_score": 33, "relevance_reason": "low", "summary": "The full summary",
         "tags": ["ai"], "fits": False, "confidence": 0.9},
    ])
    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher, bypass_gate=True)
    assert out["summary"] == "The full summary"  # fetched + summarized despite the low score
    with Session(engine_with_card) as s:
        card = s.get(Card, 1)
    assert card.summary == "The full summary" and card.curated is True
    stored = get_fulltext(engine_with_card, 1)
    assert stored is not None and "full body text" in (stored["markdown"] or "")


def test_relevant_path_fetches_and_recommends(engine_with_card, tmp_path):
    def fetcher(url):
        return {"markdown": "full body", "status": "ok", "content_type": "", "source_url": url}
    llm = _llm([
        {"relevance_score": 80, "relevance_reason": "yes", "summary": "", "tags": [], "fits": False, "confidence": 0.8},
        {"relevance_score": 85, "relevance_reason": "yes", "summary": "Deep summary", "tags": ["ai"], "category": "AI", "fits": True, "confidence": 0.9},
    ])
    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)
    assert out["recommended"] is True
    with Session(engine_with_card) as s:
        card = s.get(Card, 1)
    assert card.summary == "Deep summary" and card.category == "AI" and card.curated is True
    assert card.relevance_score == 85


def test_hypothesis_breaks_keeps_summary_not_recommended(engine_with_card, tmp_path):
    def fetcher(url):
        return {"markdown": "body", "status": "ok", "content_type": "", "source_url": url}
    llm = _llm([
        {"relevance_score": 70, "relevance_reason": "maybe", "summary": "", "tags": [], "fits": False, "confidence": 0.7},
        {"relevance_score": 20, "relevance_reason": "off", "summary": "Sum", "tags": [], "fits": False, "confidence": 0.7},
    ])
    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)
    assert out["recommended"] is False
    with Session(engine_with_card) as s:
        assert s.get(Card, 1).summary == "Sum"


def test_fetch_failure_degrades_gracefully(engine_with_card, tmp_path):
    def fetcher(url):
        return {"markdown": "", "status": "failed", "error": "HTTP 503", "content_type": "", "source_url": url}
    llm = _llm([{"relevance_score": 80, "relevance_reason": "y", "summary": "", "tags": [], "fits": False, "confidence": 0.8}])
    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)
    # Gate 1 passed but no full text -> judged on blurb, not recommended, no crash.
    assert out is not None and out["recommended"] is False


def test_structured_failure_fields_pass_through_to_store_fulltext(engine_with_card, tmp_path):
    """When the fetcher returns the structured-failure fields (as
    documents.fetch_fulltext now does on give-up), enrich_item threads them through
    to store_fulltext -- the stored Content row carries the same structured record,
    not just markdown/status/error."""
    from spyglass_service.content_store import get_fulltext

    def fetcher(url):
        return {
            "markdown": "", "status": "failed",
            "error": "blocked at T0 (HTTP 403); T1 also failed: timeout",
            "content_type": "", "source_url": url,
            "detected_type": "html", "tier_reached": "T1",
            "http_status": 403, "error_class": "blocked",
        }

    llm = _llm([{"relevance_score": 80, "relevance_reason": "y", "summary": "", "tags": [], "fits": False, "confidence": 0.8}])
    enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)

    stored = get_fulltext(engine_with_card, 1)
    assert stored is not None
    assert stored["detected_type"] == "html"
    assert stored["tier_reached"] == "T1"
    assert stored["http_status"] == 403
    assert stored["error_class"] == "blocked"
    assert "403" in stored["error"]


def test_structured_failure_fields_absent_from_fetcher_default_to_none(engine_with_card, tmp_path):
    """A fetcher/lane whose dict has no structured keys still stores
    cleanly -- store_fulltext's new kwargs are all optional/defaulted."""
    from spyglass_service.content_store import get_fulltext

    def fetcher(url):
        return {"markdown": "full body", "status": "ok", "content_type": "", "source_url": url}

    llm = _llm([
        {"relevance_score": 80, "relevance_reason": "yes", "summary": "", "tags": [], "fits": False, "confidence": 0.8},
        {"relevance_score": 85, "relevance_reason": "yes", "summary": "Deep summary", "tags": ["ai"], "category": "AI", "fits": True, "confidence": 0.9},
    ])
    enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)

    stored = get_fulltext(engine_with_card, 1)
    assert stored["detected_type"] is None
    assert stored["tier_reached"] is None
    assert stored["http_status"] is None
    assert stored["error_class"] is None


def test_enrich_pending_skips_already_judged(engine_with_two_cards, tmp_path):
    # card 1 already judged (relevance_at set), card 2 fresh
    def fetcher(url):
        return {"markdown": "b", "status": "ok", "content_type": "", "source_url": url}
    llm = _llm([{"relevance_score": 5, "relevance_reason": "n", "summary": "", "tags": [], "fits": False, "confidence": 0.9}])
    res = enrich_pending(engine_with_two_cards, _index(), _settings(tmp_path), llm=llm, fetcher=fetcher)
    assert res["judged"] == 1  # only the fresh card


def test_run_scheduled_enrich_skips_when_fresh_unless_forced(engine_with_two_cards, tmp_path):
    """The 24h guard skips a fresh run, but force=True runs it anyway so newly-collected
    items are judged promptly. enrich_pending self-limits to unjudged cards."""
    # A recent successful enrich run makes the daily guard consider us "fresh".
    with Session(engine_with_two_cards) as s:
        s.add(RunLog(source="enrich", status="ok", started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
        s.commit()

    def fetcher(url):
        return {"markdown": "b", "status": "ok", "content_type": "", "source_url": url}

    llm = _llm([{"relevance_score": 5, "relevance_reason": "n", "summary": "", "tags": [], "fits": False, "confidence": 0.9}])
    # Not forced + fresh -> skipped (returns None, no LLM call consumed).
    assert run_scheduled_enrich(engine_with_two_cards, _index(), _settings(tmp_path), force=False, llm=llm, fetcher=fetcher) is None
    # Forced -> runs despite freshness; the one pending card (id 2) gets judged.
    tally = run_scheduled_enrich(engine_with_two_cards, _index(), _settings(tmp_path), force=True, llm=llm, fetcher=fetcher)
    assert tally is not None and tally["judged"] == 1


def test_embed_failure_does_not_break_enrichment(engine_with_card, tmp_path):
    """A failing embed must not lose the summary or raise -- the summary is the valuable
    output; the embedding is a backfillable extra (regression: on-demand /fulltext 500'd
    when the embed model file was missing)."""
    def fetcher(url):
        return {"markdown": "full body", "status": "ok", "content_type": "", "source_url": url}
    llm = _llm([
        {"relevance_score": 80, "relevance_reason": "yes", "summary": "", "tags": [], "fits": False, "confidence": 0.8},
        {"relevance_score": 85, "relevance_reason": "yes", "summary": "Deep summary", "tags": ["ai"], "category": "AI", "fits": True, "confidence": 0.9},
    ])

    def boom(_texts):  # embed model unavailable -> embed_one raises
        raise RuntimeError("embed model file missing")

    bad_index = EmbeddingIndex(boom, "fake", 4)
    out = enrich_item(engine_with_card, bad_index, _settings(tmp_path), 1, llm=llm, fetcher=fetcher)
    # Enrichment still succeeds and the summary is persisted, despite the embed failure.
    assert out is not None and out["recommended"] is True and out["summary"] == "Deep summary"
    with Session(engine_with_card) as s:
        card = s.get(Card, 1)
    assert card.summary == "Deep summary" and card.curated is True


def test_bypass_gate_skips_gate1_entirely(engine_with_card, tmp_path):
    """A manual fetch (bypass_gate=True) skips the Gate-1 LLM call -- the sole LLM call
    is Gate-2 on the full text. No LLM prerequisite before the fetch."""
    calls = {"n": 0}

    def llm(messages):
        calls["n"] += 1
        return {"relevance_score": 85, "relevance_reason": "y", "summary": "S",
                "tags": [], "fits": False, "confidence": 0.9}

    def fetcher(url):
        return {"markdown": "body", "status": "ok", "content_type": "", "source_url": url}

    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher, bypass_gate=True)
    assert calls["n"] == 1  # Gate-2 only; Gate-1 was skipped
    assert out["summary"] == "S" and out["recommended"] is True


def test_bypass_gate_gate2_failure_keeps_text_and_does_not_raise(engine_with_card, tmp_path):
    """On the manual path, a Gate-2 LLM failure must not lose the fetched text or 500
    the endpoint -- the text is already stored; return a partial result."""
    from spyglass_service.content_store import get_fulltext

    def llm(messages):
        raise RuntimeError("OpenRouter down / no key")

    def fetcher(url):
        return {"markdown": "full body text", "status": "ok", "content_type": "", "source_url": url}

    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher, bypass_gate=True)
    assert out is not None and out["summary"] == "" and out["recommended"] is False
    assert out["relevance_score"] is None  # no judgment on a failed manual enrichment
    stored = get_fulltext(engine_with_card, 1)
    assert stored is not None and "full body text" in (stored["markdown"] or "")


def test_no_injected_fetcher_calls_fetch_fulltext_with_settings_and_engine(
    engine_with_card, tmp_path, monkeypatch
):
    """With NO injected fetcher, enrich_item must call the real
    documents.fetch_fulltext, passing the settings/engine it already has in scope --
    this is what activates the full ladder (Jina/browser toggles) + per-domain cache in
    production (both the automatic pass and, via the fetch queue, the manual button).
    Calling fetch_fulltext(url) bare would silently run the curl-only fallback ladder
    with no per-domain cache. Spies on enrich.fetch_fulltext (the name enrich_item
    resolves via `fetcher or fetch_fulltext`) rather than documents.fetch_fulltext, since
    enrich imports the function into its own module namespace.
    """
    import spyglass_service.enrich as enrich_module

    captured = {}

    def spy_fetch_fulltext(url, *, settings=None, engine=None):
        captured["url"] = url
        captured["settings"] = settings
        captured["engine"] = engine
        return {"markdown": "full body", "status": "ok", "content_type": "", "source_url": url}

    monkeypatch.setattr(enrich_module, "fetch_fulltext", spy_fetch_fulltext)

    settings = _settings(tmp_path)
    llm = _llm([
        {"relevance_score": 80, "relevance_reason": "yes", "summary": "", "tags": [], "fits": False, "confidence": 0.8},
        {"relevance_score": 85, "relevance_reason": "yes", "summary": "Deep summary", "tags": ["ai"], "category": "AI", "fits": True, "confidence": 0.9},
    ])
    out = enrich_item(engine_with_card, _index(), settings, 1, llm=llm)  # no fetcher kwarg
    assert out["summary"] == "Deep summary"
    assert captured["settings"] is settings
    assert captured["engine"] is engine_with_card


def test_injected_fetcher_still_called_as_fetcher_url_only(engine_with_card, tmp_path, monkeypatch):
    """Seam check: when a fetcher IS injected (as every other test in this file does),
    it must still be called as fetcher(url) -- no settings/engine kwargs leak into the
    test seam. Also spies on enrich.fetch_fulltext to prove the REAL fetcher is never
    touched when a stub is injected."""
    import spyglass_service.enrich as enrich_module

    real_fetch_calls = {"n": 0}
    monkeypatch.setattr(
        enrich_module, "fetch_fulltext",
        lambda *a, **k: real_fetch_calls.__setitem__("n", real_fetch_calls["n"] + 1) or {},
    )

    received = {}

    def fetcher(url):
        received["url"] = url
        return {"markdown": "full body", "status": "ok", "content_type": "", "source_url": url}

    llm = _llm([
        {"relevance_score": 80, "relevance_reason": "yes", "summary": "", "tags": [], "fits": False, "confidence": 0.8},
        {"relevance_score": 85, "relevance_reason": "yes", "summary": "Deep summary", "tags": ["ai"], "category": "AI", "fits": True, "confidence": 0.9},
    ])
    out = enrich_item(engine_with_card, _index(), _settings(tmp_path), 1, llm=llm, fetcher=fetcher)
    assert out["summary"] == "Deep summary"
    assert received["url"]  # fetcher(url) received a single positional url arg
    assert real_fetch_calls["n"] == 0  # the real fetch_fulltext was never called
