"""Tests for the in-memory embedding index, using a deterministic fake embedder."""

import numpy as np
from sqlmodel import Session, select

# Capture the REAL factory at import time -- conftest autouse-patches the module attribute
# `spyglass_service.embeddings.fastembed_embedder`, so this alias keeps a handle to the original.
from spyglass_service.embeddings import EmbeddingIndex, embed_summary, summary_text
from spyglass_service.embeddings import fastembed_embedder as _real_fastembed_embedder
from spyglass_service.models import Embedding


def _fake_embed(texts):
    # Deterministic 3-dim vectors: hash each text to a stable small vector.
    out = []
    for t in texts:
        h = abs(hash(t))
        out.append([(h % 7) + 1, (h // 7 % 7) + 1, (h // 49 % 7) + 1])
    return np.array(out, dtype=np.float32)


def _index():
    return EmbeddingIndex(embed_fn=_fake_embed, model="fake", dim=3)


def test_embed_one_returns_normalized_bytes():
    idx = _index()
    b = idx.embed_one("hello")
    v = np.frombuffer(b, dtype=np.float32)
    assert v.shape == (3,)
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_similar_returns_nearest_excluding_self():
    idx = _index()
    for i, t in enumerate(["alpha", "beta", "gamma"], start=1):
        idx.add(i, idx.embed_one(t))
    # Add a near-duplicate of item 1's text under a new id.
    idx.add(4, idx.embed_one("alpha"))
    nn = idx.similar(1, k=3)
    ids = [cid for cid, _ in nn]
    assert 1 not in ids                 # excludes self
    assert ids[0] == 4                  # the duplicate is nearest
    assert nn[0][1] > 0.99             # cosine ~1 for identical vectors


def test_remove_drops_the_vector():
    idx = _index()
    idx.add(1, idx.embed_one("alpha"))
    idx.add(2, idx.embed_one("beta"))
    idx.remove(1)
    assert not idx.has(1)
    assert [cid for cid, _ in idx.similar(2, k=5)] == []  # only self left


def test_similar_unknown_item_is_empty():
    idx = _index()
    idx.add(1, idx.embed_one("alpha"))
    assert idx.similar(999) == []


def _engine(tmp_path):
    from spyglass_service.db import create_db_engine, init_db
    engine = create_db_engine(tmp_path / "spy.db")
    init_db(engine)
    return engine


def _seed_card(engine, ext_id, title, summary):
    from sqlmodel import Session

    from spyglass_service.models import Card, Item
    with Session(engine) as session:
        item = Item(source="rss", external_id=ext_id, title=title, url="https://x.test", summary=summary)
        session.add(item)
        session.commit()
        session.refresh(item)
        session.add(Card(item_id=item.id, summary=summary))
        session.commit()
        return item.id


def test_embed_pending_embeds_carded_items(tmp_path):
    from spyglass_service.embeddings import embed_pending
    engine = _engine(tmp_path)
    _seed_card(engine, "a", "Alpha", "about alpha")
    _seed_card(engine, "b", "Beta", "about beta")
    idx = _index()
    n = embed_pending(engine, idx)
    assert n == 2
    assert idx.has(1) and idx.has(2)


def test_embed_pending_is_idempotent(tmp_path):
    from spyglass_service.embeddings import embed_pending
    engine = _engine(tmp_path)
    _seed_card(engine, "a", "Alpha", "about alpha")
    idx = _index()
    assert embed_pending(engine, idx) == 1
    assert embed_pending(engine, idx) == 0  # nothing new


def test_load_from_db_rebuilds_index(tmp_path):
    from spyglass_service.embeddings import embed_pending
    engine = _engine(tmp_path)
    _seed_card(engine, "a", "Alpha", "about alpha")
    embed_pending(engine, _index())          # writes rows with one index instance
    fresh = _index()                          # a brand-new index (cold)
    assert fresh.load_from_db(engine) == 1
    assert fresh.has(1)


def test_embed_pending_is_concurrency_safe(tmp_path):
    """Two concurrent embed_pending calls on the same engine+index must not raise
    IntegrityError and must produce exactly N Embedding rows (no duplicates).

    Uses the module-level _embed_lock to serialize concurrent callers so the
    second thread acquires the lock after the first finishes, finds nothing
    pending, and returns 0.
    """
    import concurrent.futures

    from sqlmodel import Session, select

    from spyglass_service.embeddings import embed_pending
    from spyglass_service.models import Embedding

    engine = _engine(tmp_path)
    _seed_card(engine, "a", "Alpha", "about alpha")
    _seed_card(engine, "b", "Beta", "about beta")
    _seed_card(engine, "c", "Gamma", "about gamma")
    idx = _index()

    errors: list[BaseException] = []

    def run() -> int:
        """Call embed_pending, capturing any exception."""
        try:
            return embed_pending(engine, idx)
        except Exception as exc:
            errors.append(exc)
            return -1

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run), pool.submit(run)]
        concurrent.futures.wait(futures)

    assert errors == [], f"Concurrent embed_pending raised: {errors}"

    with Session(engine) as session:
        rows = session.exec(select(Embedding)).all()

    assert len(rows) == 3, f"Expected 3 Embedding rows, got {len(rows)}"
    assert idx.has(1) and idx.has(2) and idx.has(3)


def test_fastembed_embedder_passes_cache_dir(monkeypatch, tmp_path):
    """fastembed_embedder forwards cache_dir to TextEmbedding so the model lands in the data dir."""
    captured = {}

    class _FakeTextEmbedding:
        def __init__(self, model_name, cache_dir=None):
            captured["model_name"] = model_name
            captured["cache_dir"] = cache_dir

        def embed(self, texts):
            return [np.zeros(3, dtype=np.float32) for _ in texts]

    monkeypatch.setattr("fastembed.TextEmbedding", _FakeTextEmbedding)
    embed = _real_fastembed_embedder(cache_dir=str(tmp_path / "models"))
    embed(["hello"])  # triggers the lazy import + model construction
    assert captured["cache_dir"] == str(tmp_path / "models")


def test_ensure_index_uses_models_dir_as_cache(monkeypatch, tmp_path):
    """ServiceState.ensure_index builds the embedder with cache_dir = settings.models_dir."""
    from spyglass_service.config import Settings
    from spyglass_service.db import create_db_engine, init_db
    from spyglass_service.mcp_server import ServiceState

    captured = {}

    def _spy(*args, cache_dir=None, **kwargs):
        captured["cache_dir"] = cache_dir
        return _fake_embed

    monkeypatch.setattr("spyglass_service.embeddings.fastembed_embedder", _spy)
    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    state = ServiceState(settings=settings, engine=engine)
    state.ensure_index()
    assert captured["cache_dir"] == str(settings.models_dir)


# ---------------------------------------------------------------------------
# The deep / mean-pool API is retired.
# ---------------------------------------------------------------------------

def test_deep_embedding_removed():
    """The deep (whole-body, mean-pooled) embedding surface no longer exists on the module or index."""
    import spyglass_service.embeddings as emb
    assert not hasattr(emb, "embed_doc")
    assert not hasattr(emb, "chunk_text")
    assert not hasattr(emb, "deep_text")
    assert not hasattr(emb, "embed_deep_pending")
    assert not hasattr(emb, "embed_card_deep")
    assert not hasattr(emb, "CHUNK_CHARS")
    assert not hasattr(EmbeddingIndex, "embed_doc")


def _store_content(engine, item_id, markdown, status="ok"):
    from spyglass_service.content_store import store_fulltext
    store_fulltext(engine, item_id=item_id, markdown=markdown, status=status)


# ---------------------------------------------------------------------------
# embed_pending_all is now shallow-only (returns an int count).
# ---------------------------------------------------------------------------

def test_embed_pending_all_is_shallow_only(tmp_path):
    """embed_pending_all returns the shallow count and embeds every carded item once,
    regardless of whether stored full text exists (deep upgrades are retired)."""
    from spyglass_service.embeddings import embed_pending_all
    engine = _engine(tmp_path)
    iid = _seed_card(engine, "a", "Alpha", "about alpha")
    _seed_card(engine, "b", "Beta", "about beta")
    _store_content(engine, iid, "a body that is no longer deep-embedded")
    assert embed_pending_all(engine, _index()) == 2


def test_embed_pending_all_is_idempotent(tmp_path):
    """A second pass finds nothing pending and returns 0."""
    from spyglass_service.embeddings import embed_pending_all
    engine = _engine(tmp_path)
    _seed_card(engine, "a", "Alpha", "about alpha")
    idx = _index()
    assert embed_pending_all(engine, idx) == 1
    assert embed_pending_all(engine, idx) == 0


def test_embed_pending_all_writes_shallow_source(tmp_path):
    """The single embedding row a content-bearing item gets is text_source='shallow'."""
    from sqlmodel import Session, select

    from spyglass_service.embeddings import embed_pending_all
    from spyglass_service.models import Embedding
    engine = _engine(tmp_path)
    iid = _seed_card(engine, "a", "Alpha", "about alpha")
    _store_content(engine, iid, "deep body that is now ignored")
    embed_pending_all(engine, _index())
    with Session(engine) as s:
        rows = s.exec(select(Embedding).where(Embedding.item_id == iid)).all()
    assert len(rows) == 1 and rows[0].text_source == "shallow"


# ---------------------------------------------------------------------------
# build_embedder seam + summary_text + embed_summary
# ---------------------------------------------------------------------------


def _fake_index():
    """Build a 4-dim fake EmbeddingIndex for summary tests."""
    return EmbeddingIndex(lambda texts: np.ones((len(texts), 4), dtype=np.float32), "fake", 4)


def test_summary_text_composes_heading_summary_tags():
    """summary_text must include the title, summary, and each tag in its output."""
    out = summary_text("Title", "A summary.", ["ai", "health"])
    assert "Title" in out and "A summary." in out and "ai" in out and "health" in out


def test_embed_summary_upserts_summary_source(engine_with_item):
    """embed_summary must write a 'summary' text_source Embedding and add it to the index."""
    index = _fake_index()
    embed_summary(engine_with_item, index, 1, "T", "S", ["x"])
    with Session(engine_with_item) as s:
        row = s.exec(select(Embedding).where(Embedding.item_id == 1)).one()
    assert row.text_source == "summary" and row.dim == 4
    assert index.has(1)


def test_matrix_for_returns_present_vectors_in_requested_order():
    """matrix_for returns (found_ids, matrix) for the subset of ids present, in request order."""
    idx = _index()
    for i, t in enumerate(["alpha", "beta", "gamma"], start=1):
        idx.add(i, idx.embed_one(t))
    found, matrix = idx.matrix_for([3, 99, 1])  # 99 is absent
    assert found == [3, 1]
    assert matrix.shape == (2, 3)
    # Row 0 is item 3's stored vector, row 1 is item 1's.
    assert np.allclose(matrix[0], np.frombuffer(idx.embed_one("gamma"), dtype=np.float32))


def test_matrix_for_empty_when_none_present():
    """matrix_for on all-absent ids yields no rows and a (0, dim) matrix."""
    idx = _index()
    idx.add(1, idx.embed_one("alpha"))
    found, matrix = idx.matrix_for([42, 43])
    assert found == []
    assert matrix.shape == (0, 3)
