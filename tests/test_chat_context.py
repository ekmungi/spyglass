# tests/test_chat_context.py
"""Tests for the chat send path: prompt order, budget, and legible degradation.

Two properties carry the design and are pinned hardest here:

1. **Card text is the stable prefix.** It goes before the conversation so implicit prefix
   caching makes it near-free on follow-ups, and the question goes last.
2. **Nothing is dropped silently.** An oversized selection must SAY what it trimmed -- a
   quietly truncated context that yields a confidently wrong answer is the worst outcome
   available here.
"""

from spyglass_service.chat_context import (
    DEFAULT_CONTEXT_WINDOW,
    CardContext,
    build_card_blocks,
    build_prompt,
    context_budget,
    estimate_tokens,
    split_for_rollover,
)


def _card(name: str, *, fulltext: str | None = "body " * 50, summary: str = "a summary") -> CardContext:
    return CardContext(card_id=abs(hash(name)) % 1000, title=name, source="test",
                       summary=summary, fulltext=fulltext)


# ---------------------------------------------------------------------------
# Budget arithmetic
# ---------------------------------------------------------------------------


def test_estimate_scales_with_length_and_is_never_zero_for_real_text():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)
    assert estimate_tokens("hello") >= 1


def test_budget_is_a_fraction_of_the_model_window_not_a_constant():
    """Models differ by an order of magnitude, so the budget must scale."""
    big = context_budget("deepseek/deepseek-v4-flash")
    small = context_budget("deepseek/deepseek-v4-flash", window=8_000)
    assert big > small
    assert small < 8_000  # a fraction of it, never the whole window


def test_an_unknown_model_falls_back_conservatively_rather_than_guessing_big():
    assert context_budget("someone/brand-new-model") <= context_budget(
        "someone/brand-new-model", window=DEFAULT_CONTEXT_WINDOW
    )
    assert context_budget("someone/brand-new-model") < DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Card blocks: the pinned prefix, and legible degradation
# ---------------------------------------------------------------------------


def test_a_card_block_carries_title_source_and_full_text():
    built = build_card_blocks([_card("Alpha", fulltext="THE BODY TEXT")], budget=10_000)
    blob = "\n".join(built.blocks)
    assert "Alpha" in blob and "THE BODY TEXT" in blob
    assert built.trimmed == [] and built.summarised == []


def test_a_card_with_no_full_text_is_named_not_silently_thinned():
    """A card with no full text is named plainly, so the pane can offer to fetch it."""
    built = build_card_blocks([_card("Alpha", fulltext=None)], budget=10_000)
    assert built.missing_fulltext == ["Alpha"]
    assert "a summary" in "\n".join(built.blocks)  # the summary still goes in


def test_an_oversized_selection_falls_back_to_summaries_and_says_which():
    """Degrade legibly, never silently."""
    cards = [_card(f"Card{i}", fulltext="x" * 20_000) for i in range(5)]
    built = build_card_blocks(cards, budget=1_000)

    assert built.summarised, "an over-budget selection must report what it reduced"
    assert set(built.summarised) <= {c.title for c in cards}
    assert built.notice, "there must be a human-readable notice to show in the pane"
    for name in built.summarised:
        assert name in built.notice


def test_the_budget_is_actually_respected_when_the_selection_is_huge():
    cards = [_card(f"Card{i}", fulltext="x" * 20_000) for i in range(5)]
    built = build_card_blocks(cards, budget=1_000)
    assert estimate_tokens("\n".join(built.blocks)) <= 1_000


def test_a_selection_that_fits_is_left_completely_alone():
    cards = [_card("Alpha", fulltext="short body"), _card("Beta", fulltext="also short")]
    built = build_card_blocks(cards, budget=10_000)
    assert built.trimmed == [] and built.summarised == [] and built.notice is None


def test_trimming_prefers_shrinking_the_biggest_card_first():
    """A single monster article must not cost every other card its text."""
    cards = [_card("Small", fulltext="tiny"), _card("Monster", fulltext="x" * 40_000)]
    built = build_card_blocks(cards, budget=600)
    assert "Monster" in (built.summarised + built.trimmed)
    assert "Small" not in built.summarised
    assert "tiny" in "\n".join(built.blocks)


# ---------------------------------------------------------------------------
# Prompt assembly: order is the whole point
# ---------------------------------------------------------------------------


def test_prompt_order_is_cards_then_history_then_the_question_last():
    messages = build_prompt(
        card_blocks=["CARD BLOCK"],
        rolled_summary="EARLIER SUMMARY",
        recent=[{"role": "user", "content": "OLDER Q"}, {"role": "assistant", "content": "OLDER A"}],
        question="THE NEW QUESTION",
    )
    blob = "\n".join(m["content"] for m in messages)
    assert blob.index("CARD BLOCK") < blob.index("EARLIER SUMMARY") < blob.index("OLDER Q")
    assert blob.index("OLDER Q") < blob.index("THE NEW QUESTION")
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "THE NEW QUESTION"


def test_the_first_message_is_the_system_prompt_so_the_prefix_is_stable():
    messages = build_prompt(card_blocks=["CARD"], rolled_summary=None, recent=[], question="Q")
    assert messages[0]["role"] == "system"


def test_a_thread_with_no_history_still_produces_a_valid_prompt():
    messages = build_prompt(card_blocks=["CARD"], rolled_summary=None, recent=[], question="Q")
    assert [m["role"] for m in messages][-1] == "user"
    assert all(m["content"] for m in messages)


def test_recent_turns_are_sent_verbatim():
    recent = [{"role": "user", "content": "exact words"}, {"role": "assistant", "content": "exact reply"}]
    messages = build_prompt(card_blocks=[], rolled_summary=None, recent=recent, question="Q")
    assert {"role": "user", "content": "exact words"} in messages
    assert {"role": "assistant", "content": "exact reply"} in messages


# ---------------------------------------------------------------------------
# Rollover
# ---------------------------------------------------------------------------


def test_a_short_thread_never_rolls_over():
    turns = [{"role": "user", "content": "hi"}] * 4
    older, recent = split_for_rollover(turns, recent_turns=8)
    assert older == [] and recent == turns


def test_a_long_thread_keeps_the_recent_window_verbatim_and_offers_the_rest():
    turns = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    older, recent = split_for_rollover(turns, recent_turns=6)
    assert len(recent) == 6
    assert recent == turns[-6:]
    assert older == turns[:-6]
    # Nothing is lost in the split -- compaction changes the PROMPT, never the transcript.
    assert older + recent == turns
