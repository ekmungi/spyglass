"""Tests for the Recategorize pass adapter + orchestration.

Vectors are added to the index directly (bypassing the embedder) so similarity is fully
controlled and clusters are deterministic. dim=4 keeps the crafted vectors readable.
"""

import json
from datetime import UTC, datetime

import numpy as np
from sqlmodel import Session, select

from spyglass_service.categories import add_category
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Card, Category, CardState, Item, RunLog
from spyglass_service.recategorize import (
    accept_candidate,
    build_candidates,
    is_recategorize_running,
    latest_candidates,
    reclassify_unsorted,
    run_recategorize,
)


def _unit(*comps: float) -> bytes:
    """A unit-normalized float32 vector as stored bytes (the index stores normalized vectors)."""
    v = np.array(comps, dtype=np.float32)
    norm = float(np.linalg.norm(v))
    return (v / norm if norm else v).tobytes()


def _make(tmp_path):
    """Fresh engine + a dim=4 index whose embed_fn is unused (vectors are added directly)."""
    engine = create_db_engine(tmp_path / "recat.db")
    init_db(engine)
    index = EmbeddingIndex(lambda texts: np.zeros((len(texts), 4), dtype=np.float32), "test", 4)
    return engine, index


def _seed(engine, index, *, ext, title, vector, category=None, override=False,
          state=CardState.NEW) -> tuple[int, int]:
    """Insert one Item+Card, register its vector in the index, return (card_id, item_id)."""
    with Session(engine) as session:
        item = Item(source="test", external_id=ext, title=title, url=f"https://x.test/{ext}")
        session.add(item)
        session.flush()
        card = Card(item_id=item.id, summary=f"summary {title}", category=category,
                    category_override=override, state=state)
        session.add(card)
        session.commit()
        cid, iid = card.id, item.id
    if category is not None:
        # A card's category is always in the managed registry (the _ensure_category invariant);
        # register it here so the seeded state is realistic.
        add_category(engine, category)
    if vector is not None:
        index.add(iid, vector)
    return cid, iid


# --- reclassify_unsorted (LLM enum re-classify) ----------------------------------------------


def test_reclassify_files_cards_via_the_classifier(tmp_path) -> None:
    """Each Unsorted card is filed into the category the classifier returns for it."""
    engine, index = _make(tmp_path)
    add_category(engine, "Healthcare AI")
    add_category(engine, "Robotics")
    h, _ = _seed(engine, index, ext="u1", title="Clinical LLM", vector=None)
    r, _ = _seed(engine, index, ext="u2", title="Robot arm", vector=None)

    def clf(title, summary, tags):  # a stub classifier keyed on a title keyword
        return "Robotics" if "Robot" in title else "Healthcare AI"

    assert reclassify_unsorted(engine, settings=None, classifier=clf) == 2
    with Session(engine) as session:
        assert session.get(Card, h).category == "Healthcare AI"
        assert session.get(Card, r).category == "Robotics"


def test_reclassify_leaves_card_unsorted_on_null(tmp_path) -> None:
    """A classifier returning None (nothing fits) leaves the card Unsorted -- never force-fit."""
    engine, index = _make(tmp_path)
    add_category(engine, "Healthcare AI")
    cid, _ = _seed(engine, index, ext="u1", title="Wordle hints", vector=None)
    assert reclassify_unsorted(engine, settings=None, classifier=lambda t, s, tg: None) == 0
    with Session(engine) as session:
        assert session.get(Card, cid).category is None


def test_reclassify_never_touches_overridden_card(tmp_path) -> None:
    """A user-overridden card is excluded from the re-classify pass."""
    engine, index = _make(tmp_path)
    add_category(engine, "Healthcare AI")
    cid, _ = _seed(engine, index, ext="u1", title="X", vector=None, override=True)
    assert reclassify_unsorted(engine, settings=None, classifier=lambda t, s, tg: "Healthcare AI") == 0
    with Session(engine) as session:
        assert session.get(Card, cid).category is None


def test_reclassify_no_categories_is_a_no_op(tmp_path) -> None:
    """With no managed categories, there is nothing to file into and the LLM is never called."""
    engine, index = _make(tmp_path)
    _seed(engine, index, ext="u1", title="X", vector=None)
    called: list[int] = []
    assigned = reclassify_unsorted(
        engine, settings=None, classifier=lambda t, s, tg: called.append(1) or "X"
    )
    assert assigned == 0 and called == []


def test_reclassify_survives_a_classifier_error(tmp_path) -> None:
    """One card that makes the classifier raise is skipped; the rest are still filed."""
    engine, index = _make(tmp_path)
    add_category(engine, "Healthcare AI")
    good, _ = _seed(engine, index, ext="u1", title="good", vector=None)
    bad, _ = _seed(engine, index, ext="u2", title="boom", vector=None)

    def clf(title, summary, tags):
        if title == "boom":
            raise RuntimeError("llm down")
        return "Healthcare AI"

    assert reclassify_unsorted(engine, settings=None, classifier=clf) == 1
    with Session(engine) as session:
        assert session.get(Card, good).category == "Healthcare AI"
        assert session.get(Card, bad).category is None


# --- build_candidates ------------------------------------------------------------------------


def test_build_candidates_clusters_unsorted_into_named_candidate(tmp_path) -> None:
    """A dense group of Unsorted cards becomes one candidate with a name, size, and members."""
    engine, index = _make(tmp_path)
    card_ids = []
    for i in range(8):
        # Near-identical vectors along axis 0 -> a single tight cluster.
        cid, _ = _seed(engine, index, ext=f"u{i}", title=f"Robot {i}",
                       vector=_unit(1, 0.001 * i, 0, 0))
        card_ids.append(cid)

    candidates = build_candidates(
        engine, index, threshold=0.5, min_size=8, namer=lambda titles: "Robotics Cluster"
    )
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["suggested_name"] == "Robotics Cluster"
    assert cand["size"] == 8
    assert sorted(cand["card_ids"]) == sorted(card_ids)
    assert len(cand["examples"]) == 4 and all(e.startswith("Robot ") for e in cand["examples"])


def test_build_candidates_ignores_sparse_unsorted(tmp_path) -> None:
    """When nothing forms a dense cluster, no candidate is proposed."""
    engine, index = _make(tmp_path)
    _seed(engine, index, ext="u0", title="A", vector=_unit(1, 0, 0, 0))
    _seed(engine, index, ext="u1", title="B", vector=_unit(0, 1, 0, 0))
    _seed(engine, index, ext="u2", title="C", vector=_unit(0, 0, 1, 0))

    candidates = build_candidates(
        engine, index, threshold=0.9, min_size=2, namer=lambda titles: "X"
    )
    assert candidates == []


# --- run_recategorize / latest_candidates / running-guard ------------------------------------


def test_run_recategorize_persists_runlog_and_returns_result(tmp_path) -> None:
    """A full run clusters the Unsorted pile and records an ok RunLog carrying the JSON result."""
    engine, index = _make(tmp_path)
    # No categorized cards -> nothing to reassign; a dense Unsorted cluster -> one candidate.
    for i in range(8):
        _seed(engine, index, ext=f"u{i}", title=f"Topic {i}", vector=_unit(0, 1, 0.001 * i, 0))

    result = run_recategorize(
        engine, index, settings=None, namer=lambda titles: "New Topic",
        cluster_threshold=0.5, min_size=8,
    )
    assert result["assigned"] == 0  # no categories configured -> nothing to re-classify
    assert len(result["candidates"]) == 1
    with Session(engine) as session:
        run = session.exec(select(RunLog).where(RunLog.source == "recategorize")).first()
    assert run.status == "ok"
    assert json.loads(run.detail)["candidates"][0]["suggested_name"] == "New Topic"


def test_run_recategorize_keeps_assignments_when_cluster_step_fails(tmp_path, monkeypatch) -> None:
    """A failure in the cluster step is non-fatal: assignments persist and the run is 'error'.

    Re-classify runs first and commits; if the later cluster/naming step raises, the run records
    'error' but still reports the cards it re-filed and never rolls them back.
    """
    engine, index = _make(tmp_path)
    add_category(engine, "A")
    on_a, _ = _seed(engine, index, ext="on", title="On", vector=None)

    def boom(*args, **kwargs):
        raise RuntimeError("cluster step down")

    monkeypatch.setattr("spyglass_service.recategorize.build_candidates", boom)
    result = run_recategorize(
        engine, index, settings=None, namer=lambda t: "X", classifier=lambda t, s, tg: "A",
    )
    assert result["assigned"] == 1
    assert result["candidates"] == []
    assert "error" in result
    with Session(engine) as session:
        assert session.get(Card, on_a).category == "A"  # assignment survived the failure
        run = session.exec(select(RunLog).where(RunLog.source == "recategorize")).first()
    assert run.status == "error"


def test_latest_candidates_reads_last_run(tmp_path) -> None:
    """latest_candidates surfaces the most recent run's status and candidate list."""
    engine, index = _make(tmp_path)
    for i in range(8):
        _seed(engine, index, ext=f"u{i}", title=f"Topic {i}", vector=_unit(1, 0.001 * i, 0, 0))
    run_recategorize(engine, index, settings=None, namer=lambda t: "Named",
                     cluster_threshold=0.5, min_size=8)

    latest = latest_candidates(engine)
    assert latest["status"] == "ok"
    assert latest["candidates"][0]["suggested_name"] == "Named"


def test_latest_candidates_none_when_never_run(tmp_path) -> None:
    """With no run yet, the status is 'none' and there are no candidates."""
    engine, index = _make(tmp_path)
    assert latest_candidates(engine) == {"status": "none", "candidates": []}


def test_is_recategorize_running_reflects_open_run(tmp_path) -> None:
    """A running row (no finished_at) reads as running; a finished one does not."""
    engine, _ = _make(tmp_path)
    assert is_recategorize_running(engine) is False
    with Session(engine) as session:
        session.add(RunLog(source="recategorize", status="running"))
        session.commit()
    assert is_recategorize_running(engine) is True


def test_is_recategorize_running_treats_stale_row_as_not_running(tmp_path) -> None:
    """A long-abandoned 'running' row (crash/kill mid-run) self-heals: a new kick may proceed.

    Without an age check a single crash would deadlock every future kick forever (adversarial
    review #1); a run realistically finishes in seconds, so an hour-old 'running' row is stale.
    """
    from datetime import timedelta

    engine, _ = _make(tmp_path)
    with Session(engine) as session:
        session.add(
            RunLog(
                source="recategorize", status="running",
                started_at=datetime.now(UTC) - timedelta(hours=3),  # older than the 2h stale window
            )
        )
        session.commit()
    assert is_recategorize_running(engine) is False


def test_build_candidates_skips_a_vectorless_card_without_misaligning(tmp_path) -> None:
    """A card with no embedding is skipped; alignment (review #2) keeps titles/ids matched.

    Alignment is derived from the index's atomic return, not a pre-snapshot, so a gap in the
    middle of the working set never shifts a vector onto the wrong card.
    """
    engine, index = _make(tmp_path)
    ids: list[int] = []
    for i in range(4):
        cid, _ = _seed(engine, index, ext=f"a{i}", title=f"A{i}", vector=_unit(1, 0.001 * i, 0, 0))
        ids.append(cid)
    gap, _ = _seed(engine, index, ext="gap", title="Gap", vector=None)  # middle gap, no embedding
    for i in range(4):
        cid, _ = _seed(engine, index, ext=f"b{i}", title=f"B{i}",
                       vector=_unit(1, 0.001 * (i + 4), 0, 0))
        ids.append(cid)

    cands = build_candidates(engine, index, threshold=0.5, min_size=8, namer=lambda t: "X")
    assert len(cands) == 1
    assert cands[0]["size"] == 8
    assert gap not in cands[0]["card_ids"]
    assert sorted(cands[0]["card_ids"]) == sorted(ids)


# --- accept_candidate ------------------------------------------------------------------------


def test_accept_candidate_creates_category_and_assigns_cards(tmp_path) -> None:
    """Accepting a candidate registers the new category and files its cards into it."""
    engine, index = _make(tmp_path)
    c1, _ = _seed(engine, index, ext="u1", title="One", vector=_unit(1, 0, 0, 0))
    c2, _ = _seed(engine, index, ext="u2", title="Two", vector=_unit(1, 0, 0, 0))

    result = accept_candidate(engine, "New Bucket", [c1, c2])
    assert result == {"name": "New Bucket", "assigned": 2}
    with Session(engine) as session:
        assert {c.name for c in session.exec(select(Category)).all()} >= {"New Bucket"}
        assert session.get(Card, c1).category == "New Bucket"
        assert session.get(Card, c2).category == "New Bucket"
