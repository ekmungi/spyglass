# ruff: noqa: F811
"""Tests for long articles: the beginning in the system prompt, the rest chosen by the question."""

import numpy as np

from spyglass_service.radar.assist import context, passages, threads
from spyglass_service.radar.assist.engines.base import StreamEvent
from spyglass_service.radar.assist.passages import (
    head_of,
    passages_block,
    select_passages,
    split_passages,
    word_scorer,
)

from .test_assist_support import (
    FakeEngine,
    add_item,
    clean_assist_env,  # noqa: F401
    db,  # noqa: F401
    make_settings,
    patch_fake_engine,
)


def article() -> str:
    """A long article whose middle section is the only one that mentions the harbour crane."""
    filler = "".join(f"Paragraph {n} talks about general matters of the industry. " * 6 + "\n\n"
                     for n in range(60))
    return filler + "The harbour crane was lifted by the new robot arm. " * 8 + "\n\n" + filler


class FakeIndex:
    """An embedding index whose vectors say only whether a text mentions the word 'crane'."""

    model = "fake"
    dim = 2

    def embed_query(self, text: str):
        """The question's vector."""
        return np.array([1.0 if "crane" in text.lower() else 0.0, 0.1], dtype=np.float32)

    def embed_many(self, texts: list[str]):
        """One vector per text."""
        return np.array([[1.0 if "crane" in t.lower() else 0.0, 0.1] for t in texts], dtype=np.float32)


def test_head_of_returns_a_short_text_whole_and_cuts_a_long_one_at_a_paragraph_end():
    assert head_of("short", 1000) == "short"
    text = ("Sentence one is here. " * 30 + "\n\n") * 20
    head = head_of(text, 2000)
    assert 600 < len(head) <= 1200 and head.endswith(".")


def test_split_passages_covers_the_text_in_order_with_offsets():
    text = "".join(f"Paragraph number {n} has some words in it.\n\n" for n in range(100))
    parts = split_passages(text, size=300)
    assert len(parts) > 5 and [at for at, _ in parts] == sorted(at for at, _ in parts)
    assert all(text[at:at + 20].strip().startswith(piece[:20].strip()) for at, piece in parts)
    assert split_passages("") == []


def test_split_passages_gives_a_huge_text_longer_passages_instead_of_more_of_them():
    assert len(split_passages("word " * 400_000)) <= passages.MAX_CHUNKS + 2


def test_word_scorer_prefers_the_passage_with_the_questions_words():
    scores = word_scorer("What lifted the harbour crane?")(["nothing relevant", "the harbour crane was lifted"])
    assert scores[1] > scores[0] == 0


def test_select_passages_picks_the_closest_ones_in_reading_order_within_the_budget():
    text = article()
    chosen = select_passages(text, "Who lifted the harbour crane?", 3_000, index=FakeIndex())
    assert any("harbour crane" in piece for _, piece in chosen)  # the best match is always kept
    assert sum(len(piece) for _, piece in chosen) <= 3_000
    assert [at for at, _ in chosen] == sorted(at for at, _ in chosen)


def test_select_passages_without_an_index_matches_words_and_survives_an_empty_question():
    assert select_passages(article(), "harbour crane", 3_000, index=None)
    assert select_passages(article(), "   ", 3_000) == [] and select_passages("", "q", 100) == []


def test_a_failing_index_falls_back_to_matching_words():
    class Broken(FakeIndex):
        def embed_many(self, texts):
            raise RuntimeError("model could not load")

    assert select_passages(article(), "harbour crane", 3_000, index=Broken())


def test_passages_block_says_they_were_selected_and_where_they_start():
    body = article()
    shown = len(head_of(body, 4_000))
    block = passages_block(body, shown, "the harbour crane", 3_000)
    assert block.startswith("Passages selected") and "chosen because they are the closest" in block
    assert "[passage starting at character" in block and "harbour crane" in block
    assert passages_block("short", 5, "q", 100) == ""


def test_the_system_prompt_of_a_long_article_holds_only_the_beginning_and_says_so(db, monkeypatch):
    monkeypatch.setattr(context, "TEXT_BUDGET", 4_000)
    item_id = add_item(db, text=article(), url="https://example.org/long")
    system = context.build_system(db, item_id=item_id)
    assert "harbour crane" not in system and "passages from it that are closest" in system
    assert "Do not say that a section or a topic is missing" in system
    assert system == context.build_system(db, item_id=item_id, selection="the harbour crane")


def test_long_item_passages_come_from_the_rest_of_the_article(db, monkeypatch):
    monkeypatch.setattr(context, "TEXT_BUDGET", 4_000)
    item_id = add_item(db, text=article(), url="https://example.org/long")
    block = context.long_item_passages(db, item_id, "Who lifted the harbour crane?", lambda: FakeIndex())
    assert "harbour crane" in block
    short_id = add_item(db, text="A short article. " * 20, url="https://example.org/short")
    assert context.long_item_passages(db, short_id, "q", lambda: FakeIndex()) == ""


def test_a_fresh_turn_on_a_long_article_carries_the_selected_passages(db, tmp_path, monkeypatch):
    monkeypatch.setattr(context, "TEXT_BUDGET", 4_000)
    item_id = add_item(db, text=article(), url="https://example.org/long")
    engine = FakeEngine([StreamEvent.delta("ok"), StreamEvent.done()])
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="Who lifted the harbour crane?",
                          index_provider=lambda: FakeIndex()))
    call = engine.calls[0]
    last = call["messages"][-1]["content"]
    assert "Passages selected" in last and "harbour crane" in last and last.endswith("crane?")
    assert "harbour crane" not in call["system"]


def test_a_resumed_turn_does_not_resend_passages(db, tmp_path, monkeypatch):
    monkeypatch.setattr(context, "TEXT_BUDGET", 4_000)
    item_id = add_item(db, text=article(), url="https://example.org/long")
    engine = FakeEngine([StreamEvent.session("S1"), StreamEvent.delta("ok"), StreamEvent.done()])
    patch_fake_engine(monkeypatch, engine)
    tid = threads.create_or_get_thread(db, item_id=item_id)["id"]
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="First?",
                          index_provider=lambda: FakeIndex()))
    list(threads.run_turn(db, make_settings(tmp_path), tid, content="Who lifted the harbour crane?",
                          index_provider=lambda: FakeIndex()))
    assert engine.calls[1]["session"] == "S1"
    assert "Passages selected" not in engine.calls[1]["messages"][-1]["content"]


def test_a_passage_is_embedded_once_and_a_second_question_embeds_only_the_question():
    passages._VECTORS.clear()
    embedded: list[int] = []

    class Counting(FakeIndex):
        def embed_many(self, texts):
            embedded.append(len(texts))
            return super().embed_many(texts)

    index = Counting()
    first = select_passages(article(), "Who lifted the harbour crane?", 3_000, index=index)
    second = select_passages(article(), "What did the robot arm do?", 3_000, index=index)
    assert first and second and len(embedded) == 2  # one probe call, then the passages once
    assert embedded[1] > 5


def test_a_cache_cleared_by_another_thread_mid_scoring_does_not_fail_the_selection(monkeypatch):
    class ClearedOnFirstRead(dict):
        """A cache that another request empties just before the second lookup of a stored vector."""

        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            if self.reads == 2:  # the probe made the first read; this is the real scoring
                self.clear()
            return super().__getitem__(key)

    monkeypatch.setattr(passages, "_VECTORS", ClearedOnFirstRead())
    found = select_passages(article(), "Who lifted the harbour crane?", 3_000, index=FakeIndex())
    assert found and any("harbour crane" in text for _, text in found)


def test_a_scorer_that_fails_while_scoring_falls_back_to_matching_words(monkeypatch):
    def failing_scorer(index, question):
        def score(texts):
            raise KeyError("cleared")
        return score

    monkeypatch.setattr(passages, "make_scorer", failing_scorer)
    found = select_passages(article(), "Who lifted the harbour crane?", 3_000, index=FakeIndex())
    assert found and any("harbour crane" in text for _, text in found)
