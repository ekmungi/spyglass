"""Long articles: keep the beginning in the system prompt and pick the rest by the question.

An article longer than the text budget used to be cut blindly: its first 70% and its last 30%, so a
question about the middle was answered from a text that did not contain the answer. Now the system
prompt keeps only the beginning (identical on every turn, so the provider can cache it) and the
passages from the rest that are closest to the reader's question are added to the question itself.
Closeness is the cosine similarity of the embedded passage and the embedded question (the same
embedding index and the same query prefix as the feed search), or, when no index is available, the
number of the question's words the passage contains.
"""

import hashlib
import logging
import math
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

# The share of the text budget kept as the beginning; the rest of the budget is for selected passages.
HEAD_SHARE = 0.6
# A passage is a paragraph or a few merged paragraphs of about this many characters.
CHUNK_CHARS = 1_600
# At most this many passages are scored, so an enormous text cannot make a question slow: a longer
# text gets longer passages instead.
MAX_CHUNKS = 60
# Embedding a passage on the CPU takes about a fifth of a second (measured: 37 passages, 7 to 10
# seconds), so a passage's vector is kept: the next question about the same article only embeds the
# question. The memory is emptied when it holds this many vectors.
_VECTOR_LIMIT = 3_000
_VECTORS: dict[tuple[str, str], object] = {}

Scorer = Callable[[list[str]], list[float]]


def head_chars(budget: int) -> int:
    """How many characters of a long article stay in the system prompt."""
    return int(budget * HEAD_SHARE)


def head_of(body: str, budget: int) -> str:
    """The beginning of `body`, cut at a paragraph or sentence end when one is near."""
    limit = head_chars(budget)
    if len(body) <= limit:
        return body
    cut = max(body.rfind("\n\n", limit // 2, limit), body.rfind(". ", limit // 2, limit) + 1)
    return body[: cut if cut > limit // 2 else limit].rstrip()


def split_passages(text: str, size: int = CHUNK_CHARS) -> list[tuple[int, str]]:
    """(start offset, passage) pairs: paragraphs merged up to about `size` characters.

    A text so long that this would make more than `MAX_CHUNKS` passages gets longer ones.
    """
    size = max(size, math.ceil(len(text) / MAX_CHUNKS))
    passages: list[tuple[int, str]] = []
    start, current = 0, ""
    for match in re.finditer(r"\S[\s\S]*?(?:\n\s*\n|\Z)", text):
        piece = match.group(0)
        if current and len(current) + len(piece) > size:
            passages.append((start, current.strip()))
            start, current = match.start(), ""
        if not current:
            start = match.start()
        current += piece
        while len(current) > size * 2:  # one paragraph far over the size is split in the middle
            passages.append((start, current[:size].strip()))
            start, current = start + size, current[size:]
    if current.strip():
        passages.append((start, current.strip()))
    return [(at, text_) for at, text_ in passages if text_]


def word_scorer(question: str) -> Scorer:
    """Score passages by how many distinct words of the question they contain."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", question.lower())}

    def score(passages: list[str]) -> list[float]:
        """One score per passage: matching words, damped by length so long passages do not win."""
        out = []
        for passage in passages:
            found = set(re.findall(r"[a-z0-9]{3,}", passage.lower()))
            out.append(len(words & found) / math.sqrt(max(1, len(found))))
        return out

    return score


def embedding_scorer(index, question: str) -> Scorer:
    """Score passages by cosine similarity to the question, using the feed search's embedding."""
    from spyglass_service.radar import feed_search

    query = feed_search.query_vector(index, question)
    model = str(getattr(index, "model", ""))

    def score(passages: list[str]) -> list[float]:
        """One cosine per passage; passages seen before are not embedded again."""
        keys = [(model, hashlib.sha1(p.encode("utf-8")).hexdigest()) for p in passages]  # noqa: S324
        # Read the shared cache once into a local dict: another request may clear it at any moment,
        # so a key found now must not be looked up again later.
        found = {key: _VECTORS.get(key) for key in set(keys)}
        missing = [i for i, key in enumerate(keys) if found[key] is None]
        if missing:
            for i, vector in zip(missing, index.embed_many([passages[i] for i in missing]), strict=True):
                found[keys[i]] = vector
            if len(_VECTORS) + len(missing) > _VECTOR_LIMIT:
                _VECTORS.clear()
            _VECTORS.update({keys[i]: found[keys[i]] for i in missing})
        return [float(found[key] @ query) for key in keys]

    return score


def make_scorer(index, question: str) -> Scorer:
    """The embedding scorer when an index is available and works, else the word scorer."""
    if index is not None:
        try:
            scorer = embedding_scorer(index, question)
            scorer(["probe"])  # the model loads on first use; a failure falls back right here
            return scorer
        except Exception:  # noqa: BLE001 -- passages are an improvement, never a reason to fail
            logger.warning("the embedding index could not score passages; matching words instead",
                           exc_info=True)
    return word_scorer(question)


def select_passages(rest: str, question: str, budget: int, index=None) -> list[tuple[int, str]]:
    """The passages of `rest` closest to `question`, in reading order, within `budget` characters.

    Returns (offset in `rest`, passage) pairs; none when the question or the text is empty or no
    passage scores above zero.
    """
    if not question.strip() or not rest.strip() or budget <= 0:
        return []
    passages = split_passages(rest)
    texts = [p for _, p in passages]
    try:
        scores = make_scorer(index, question)(texts)
    except Exception:  # noqa: BLE001 -- passages are an improvement, never a reason to fail a turn
        logger.warning("scoring the passages failed; matching words instead", exc_info=True)
        try:
            scores = word_scorer(question)(texts)
        except Exception:  # noqa: BLE001
            logger.exception("matching words in the passages failed; sending none")
            return []
    ranked = sorted(zip(scores, passages, strict=True), key=lambda pair: pair[0], reverse=True)
    chosen: list[tuple[int, str]] = []
    used = 0
    for score, (at, passage) in ranked:
        if score <= 0:
            break
        if used + len(passage) > budget:
            continue
        chosen.append((at, passage))
        used += len(passage)
    return sorted(chosen)


def passages_block(body: str, shown: int, question: str, budget: int, index=None) -> str:
    """The text added to the reader's message for a long article, or "" when nothing applies.

    `shown` is how many characters of `body` the system prompt already holds. The block says that
    the passages were selected by similarity to the question, and where each one starts.
    """
    if len(body) <= shown:
        return ""
    rest = body[shown:]
    found = select_passages(rest, question, budget, index)
    if not found:
        return ""
    parts = [f"[passage starting at character {shown + at:,} of {len(body):,}]\n{text}"
             for at, text in found]
    return ("Passages selected from the part of the article that is not in the instructions, "
            "chosen because they are the closest to this question (this is not the whole of that "
            "part):\n\n" + "\n\n".join(parts))
