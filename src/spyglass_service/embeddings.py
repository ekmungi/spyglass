"""Local embedding index: an in-memory normalized-vector matrix with an
injectable embed function, brute-force cosine similarity, and byte (de)serialization.

The real embed function (FastEmbed/arctic-embed-s) is built lazily in app wiring; tests inject
a deterministic fake. No vector DB -- one numpy matmul is enough below ~100k vectors.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.models import Card, Embedding, Item

logger = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], np.ndarray]

# Serializes concurrent embed_pending calls so that a second caller arriving
# while a backfill is in progress waits, then finds nothing pending and returns 0
# -- preventing the UNIQUE constraint violation on Embedding.item_id.
_embed_lock = Lock()


def _normalize(v: np.ndarray) -> np.ndarray:
    """Return v scaled to unit L2 norm (so cosine == dot product); zero stays zero."""
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else v


class EmbeddingIndex:
    """In-memory item_id -> normalized float32 vector, with cosine nearest-neighbour search."""

    def __init__(self, embed_fn: EmbedFn, model: str, dim: int) -> None:
        self._embed_fn = embed_fn
        self.model = model
        self.dim = dim
        self._ids: list[int] = []
        self._matrix: np.ndarray = np.empty((0, dim), dtype=np.float32)
        self._lock = Lock()

    def embed_one(self, text: str) -> bytes:
        """Embed one string and return normalized float32 bytes (for storage)."""
        vec = _normalize(self._embed_fn([text])[0].astype(np.float32))
        return vec.tobytes()

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a query string to a normalized float32 vector (in-memory, not stored)."""
        return _normalize(self._embed_fn([text])[0].astype(np.float32))

    def has(self, item_id: int) -> bool:
        """Check if item_id is in the index."""
        return item_id in self._ids

    def add(self, item_id: int, vector: bytes) -> None:
        """Add or replace one item's vector (from stored bytes)."""
        v = np.frombuffer(vector, dtype=np.float32).reshape(1, self.dim)
        with self._lock:
            if item_id in self._ids:
                self._matrix[self._ids.index(item_id)] = v
                return
            self._ids.append(item_id)
            self._matrix = np.vstack([self._matrix, v]) if self._matrix.size else v.copy()

    def remove(self, item_id: int) -> None:
        """Remove an item's vector from the index."""
        with self._lock:
            if item_id not in self._ids:
                return
            i = self._ids.index(item_id)
            del self._ids[i]
            self._matrix = np.delete(self._matrix, i, axis=0)

    def similar(self, item_id: int, k: int = 5) -> list[tuple[int, float]]:
        """The k nearest other item_ids by cosine, highest first; [] if item_id is unknown."""
        with self._lock:
            if item_id not in self._ids or len(self._ids) < 2:
                return []
            q = self._matrix[self._ids.index(item_id)]
            scores = self._matrix @ q  # normalized -> dot product == cosine
            order = np.argsort(-scores)
            out: list[tuple[int, float]] = []
            for i in order:
                cid = self._ids[i]
                if cid == item_id:
                    continue
                out.append((cid, float(scores[i])))
                if len(out) >= k:
                    break
            return out

    def matrix_for(self, item_ids: list[int]) -> tuple[list[int], np.ndarray]:
        """Stacked vectors for the subset of item_ids present, in requested order.

        Used by the relevance model to gather label + query vectors for a batched
        cosine computation without exposing the internal matrix.

        Args:
            item_ids: Item ids to look up (absent ones are skipped).

        Returns:
            (found_ids, matrix) where found_ids preserves the requested order for the ids
            that exist and matrix is (len(found_ids), dim); an empty (0, dim) matrix when none
            are present.
        """
        with self._lock:
            pos = {iid: i for i, iid in enumerate(self._ids)}
            found = [iid for iid in item_ids if iid in pos]
            if not found:
                return [], np.empty((0, self.dim), dtype=np.float32)
            return found, np.vstack([self._matrix[pos[iid]] for iid in found])

    def load_from_db(self, engine: Engine) -> int:
        """Rebuild the in-memory matrix from stored embeddings for this model.

        Queries all Embedding rows whose model matches self.model and calls self.add
        for each, restoring the in-memory index from persisted data.
        Returns the number of rows loaded.
        """
        with Session(engine) as session:
            rows = session.exec(select(Embedding).where(Embedding.model == self.model)).all()
        for row in rows:
            self.add(row.item_id, row.vector)
        return len(rows)


ARCTIC_MODEL = "snowflake/snowflake-arctic-embed-s"
ARCTIC_DIM = 384


def fastembed_embedder(model_name: str = ARCTIC_MODEL, cache_dir: str | None = None) -> EmbedFn:
    """Build a CPU embed function backed by FastEmbed (arctic-embed-s).

    The model is imported and constructed lazily on the FIRST embed call (not at factory
    time), so building the index and loading stored vectors never trigger a download --
    only an actual embed does, and that runs in a background thread so neither startup nor
    a request ever blocks on it.

    model_name: the HuggingFace model identifier to pass to TextEmbedding.
    cache_dir: where FastEmbed downloads/caches the model (~/.spyglass/models);
        None lets FastEmbed use its own default location.
    Returns an EmbedFn that embeds a list of strings to float32 numpy arrays.
    """
    holder: dict[str, object] = {"model": None}

    def embed(texts: list[str]) -> np.ndarray:
        """Embed texts, loading the model on first call."""
        if holder["model"] is None:
            from fastembed import TextEmbedding  # lazy: heavy import + one-time model download

            holder["model"] = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        model = holder["model"]
        return np.array(list(model.embed(texts)), dtype=np.float32)  # type: ignore[attr-defined]

    return embed


def shallow_text(item: Item) -> str:
    """The text embedded at ingest: title + source summary (curation-independent)."""
    return f"{item.title}\n\n{item.summary or ''}".strip()


def embed_pending(engine: Engine, index: EmbeddingIndex) -> int:
    """Embed every item that has a Card but no Embedding row yet (idempotent). Returns the count.

    Shallow embedding: title+summary, available for ALL items without any Claude curation.

    Thread-safe: serializes concurrent callers via _embed_lock so that a second call arriving
    while a backfill is in progress waits, then finds nothing pending and returns 0 rather
    than racing to INSERT duplicate rows and raising IntegrityError.
    """
    with _embed_lock:
        embedded = 0
        with Session(engine) as session:
            carded = select(Card.item_id).distinct()
            have = select(Embedding.item_id)
            item_ids = session.exec(
                select(Item).where(Item.id.in_(carded)).where(Item.id.not_in(have))  # type: ignore[union-attr]
            ).all()
            for item in item_ids:
                vector = index.embed_one(shallow_text(item))
                session.add(
                    Embedding(
                        item_id=item.id, vector=vector, model=index.model,
                        dim=index.dim, text_source="shallow", embedded_at=datetime.now(UTC),
                    )
                )
                index.add(item.id, vector)
                embedded += 1
            session.commit()
    return embedded


def build_embedder(settings) -> EmbedFn:
    """Return the configured embed function. Only 'arctic' is implemented.

    settings: a Settings instance with .embedder (str) and .models_dir (Path).
    Warns and falls back to arctic for any unrecognised embedder name.
    Returns an EmbedFn backed by fastembed_embedder with models_dir as cache_dir.
    """
    if settings.embedder not in ("arctic", "", None):
        logger.warning("unknown embedder %r; falling back to arctic", settings.embedder)
    return fastembed_embedder(ARCTIC_MODEL, cache_dir=str(settings.models_dir))


def summary_text(title: str, summary: str, tags: list[str]) -> str:
    """Composed low-noise embed text: heading + LLM summary + tags.

    title: article title.
    summary: LLM-generated summary.
    tags: list of tag strings.
    Returns a single string with title, summary, and space-joined tags.
    """
    tag_line = (" ".join(tags)).strip()
    return f"{title}\n\n{summary}\n\n{tag_line}".strip()


def embed_summary(engine: Engine, index: EmbeddingIndex, item_id: int,
                  title: str, summary: str, tags: list[str]) -> None:
    """Embed the composed summary text and upsert the item's Embedding as text_source='summary'.

    engine: SQLAlchemy engine.
    index: the EmbeddingIndex to add the vector to.
    item_id: the Item.id to embed.
    title: article title.
    summary: LLM-generated summary.
    tags: list of tag strings.
    Creates or replaces the Embedding row for item_id with text_source='summary'.
    """
    vector = index.embed_one(summary_text(title, summary, tags))
    with _embed_lock:
        with Session(engine) as session:
            row = session.exec(select(Embedding).where(Embedding.item_id == item_id)).first()
            if row is None:
                row = Embedding(item_id=item_id, vector=vector, model=index.model, dim=index.dim)
            row.vector = vector
            row.model = index.model
            row.dim = index.dim
            row.text_source = "summary"
            row.embedded_at = datetime.now(UTC)
            session.add(row)
            session.commit()
        index.add(item_id, vector)


def embed_pending_all(engine: Engine, index: EmbeddingIndex) -> int:
    """Background embedding pass: shallow blurb embed for any item lacking an embedding."""
    return embed_pending(engine, index)
