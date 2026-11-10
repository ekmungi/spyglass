"""Assembling what gets SENT to the model for one chat turn.

These APIs are stateless, so "continuing" a conversation means replaying it. Left unmanaged a
thread grows until it crowds out the window, costs more every turn, and answers worse -- so
the send path is budgeted here.

Two ideas carry the design:

- **Card text is the stable prefix.** It goes first and stays byte-identical between turns, so
  implicit prefix caching re-reads it at cache rates instead of re-billing it. The question
  goes last. (Same ordering rule the enrichment prompt follows.)
- **Storing and sending are different problems.** Nothing here trims the transcript; rollover
  only changes the prompt. So "come back to it in four days" and "do not blow the window"
  never compete.
"""

from dataclasses import dataclass, field

# Share of the model's context window the prompt may occupy. Half leaves room for the reply
# and absorbs the error in the token estimate below.
CHAT_CONTEXT_FRACTION = 0.5
# Turns kept verbatim at the end of a thread; everything older is eligible for rollover.
CHAT_RECENT_TURNS = 8
# Context windows for models we ship a default for. Deliberately small and explicit -- an
# unknown model must not be assumed roomy.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek/deepseek-v4-flash": 128_000,
}
# Fallback window for a model we have no figure for: small enough to be safe anywhere.
DEFAULT_CONTEXT_WINDOW = 32_000
# Characters per token. A heuristic, not a tokenizer -- adding one would mean a new dependency
# and a model-specific vocabulary, and CHAT_CONTEXT_FRACTION already leaves the headroom.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class CardContext:
    """One card's contribution to the prompt. `fulltext` is None when nothing is stored."""

    card_id: int
    title: str
    source: str
    summary: str
    fulltext: str | None


@dataclass(frozen=True)
class BuiltContext:
    """Card blocks plus an honest account of what had to be cut to fit."""

    blocks: list[str]
    # Cards whose full text was shortened but kept.
    trimmed: list[str] = field(default_factory=list)
    # Cards reduced to their summary because their text could not fit at all.
    summarised: list[str] = field(default_factory=list)
    # Cards that had no stored full text to begin with (offer to fetch).
    missing_fulltext: list[str] = field(default_factory=list)
    # Human-readable notice for the pane; None when everything fitted untouched.
    notice: str | None = None


def estimate_tokens(text: str) -> int:
    """Approximate a string's token count.

    A chars/4 heuristic rather than a real tokenizer: exactness is not needed because the
    budget is a fraction of the window, and a tokenizer would add a dependency plus a
    per-model vocabulary for no decision-changing gain.
    """
    return len(text) // _CHARS_PER_TOKEN


def context_budget(model: str, *, window: int | None = None, fraction: float = CHAT_CONTEXT_FRACTION) -> int:
    """Token budget for the prompt, as a share of the model's context window.

    Never a hardcoded token count: models differ by an order of magnitude, and a
    constant would either waste a large window or overflow a small one.

    Args:
        model: Model id, used to look up a known window.
        window: Explicit window override, for tests and for callers that know better.
        fraction: Share of the window the prompt may use.

    Returns:
        The prompt budget in estimated tokens.
    """
    size = window if window is not None else MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)
    return int(size * fraction)


def _block(card: CardContext, body: str | None) -> str:
    """Render one card as a prompt block; `body` None means summary-only."""
    head = f"## {card.title}\n(source: {card.source})\n\n{card.summary}"
    return f"{head}\n\n{body}" if body else head


def build_card_blocks(cards: list[CardContext], budget: int) -> BuiltContext:
    """Render the selected cards into prompt blocks that fit `budget`, reporting every cut.

    Degradation order: keep everything if it fits; otherwise shrink the LARGEST
    cards first -- so one monster article does not cost every other card its text -- trimming
    to a head slice, and falling back to summary-only when even that will not fit.

    Whatever happens, the cuts are named in `notice`. A silently truncated context that yields
    a confidently wrong answer is the worst outcome available here.

    Args:
        cards: The selected cards, in display order (preserved in the output).
        budget: Token budget for the card section.

    Returns:
        BuiltContext with the blocks and an account of what was trimmed or summarised.
    """
    missing = [c.title for c in cards if c.fulltext is None]
    bodies: dict[int, str | None] = {c.card_id: c.fulltext for c in cards}

    def total() -> int:
        return estimate_tokens("\n\n".join(_block(c, bodies[c.card_id]) for c in cards))

    # Smallest slice worth keeping; below this a head is too stubby to be worth the confusion
    # of a truncated article, so the card drops to summary-only instead.
    min_slice = _CHARS_PER_TOKEN * 50

    trimmed: list[str] = []
    summarised: list[str] = []
    if cards and total() > budget:
        # Largest first: shrinking the monster buys the most room per card sacrificed.
        for card in sorted(cards, key=lambda c: len(bodies[c.card_id] or ""), reverse=True):
            if total() <= budget:
                break
            body = bodies[card.card_id]
            if not body:
                continue
            # Estimate a head slice from the room the other cards leave, then CORRECT it by
            # measuring: the estimate ignores block joiners and integer rounding, and landing
            # a single token over would otherwise cost the next card its whole body.
            room = budget - estimate_tokens(
                "\n\n".join(_block(c, bodies[c.card_id]) for c in cards if c.card_id != card.card_id)
            )
            head = max(0, room - estimate_tokens(_block(card, None))) * _CHARS_PER_TOKEN
            bodies[card.card_id] = body[:head] if head else None
            while head > 0 and total() > budget:
                head = int(head * 0.9) - _CHARS_PER_TOKEN
                bodies[card.card_id] = body[:head] if head > 0 else None
            if head >= min_slice:
                trimmed.append(card.title)
            else:
                bodies[card.card_id] = None
                summarised.append(card.title)

    notice = None
    if trimmed or summarised:
        parts = []
        if trimmed:
            parts.append(f"shortened: {', '.join(trimmed)}")
        if summarised:
            parts.append(f"summary only: {', '.join(summarised)}")
        notice = "The selection is larger than the context budget — " + "; ".join(parts) + "."

    return BuiltContext(
        blocks=[_block(c, bodies[c.card_id]) for c in cards],
        trimmed=trimmed,
        summarised=summarised,
        missing_fulltext=missing,
        notice=notice,
    )


_SYSTEM = (
    "You are answering questions about the articles below, for a reader who is looking at "
    "them right now. Ground every claim in the provided text. If the text does not settle "
    "the question, say so plainly rather than guessing. When several articles are provided, "
    "make clear which one you are drawing on. Be concise and concrete."
)


def build_prompt(
    *,
    card_blocks: list[str],
    rolled_summary: str | None,
    recent: list[dict],
    question: str,
) -> list[dict]:
    """Assemble the message list in the fixed prompt order.

    Order is load-bearing: system -> card text -> earlier-conversation summary -> recent turns
    verbatim -> the new question last. The leading section is what stays stable across a
    thread's turns, which is what makes prefix caching pay.

    Args:
        card_blocks: Rendered card blocks from build_card_blocks.
        rolled_summary: Condensed older turns, or None before the first rollover.
        recent: Recent turns as {role, content}, oldest first, sent verbatim.
        question: The new user question.

    Returns:
        OpenAI-style messages ready to send.
    """
    system = _SYSTEM
    if card_blocks:
        system = f"{system}\n\n# Articles\n\n" + "\n\n".join(card_blocks)
    messages: list[dict] = [{"role": "system", "content": system}]
    if rolled_summary:
        messages.append(
            {"role": "system", "content": f"# Earlier in this conversation\n\n{rolled_summary}"}
        )
    messages.extend(recent)
    messages.append({"role": "user", "content": question})
    return messages


def split_for_rollover(
    turns: list[dict], recent_turns: int = CHAT_RECENT_TURNS
) -> tuple[list[dict], list[dict]]:
    """Split a transcript into (older, recent); `older` is what a rollover would condense.

    Returns an empty `older` while the thread is short, so nothing is condensed until there is
    a reason. Rolling in large infrequent steps is deliberate: each rollover invalidates the
    prefix cache from the summary onward, so trimming a turn at a time would pay that cost
    constantly.
    """
    if len(turns) <= recent_turns:
        return [], list(turns)
    return list(turns[:-recent_turns]), list(turns[-recent_turns:])
