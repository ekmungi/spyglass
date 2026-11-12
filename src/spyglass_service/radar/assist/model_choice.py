"""The "Automatic" model: the engine's cheaper model for simple turns, its stronger one for drafts.

Explaining something and answering a short question need little reasoning; writing a message or a
post for the reader to send, or answering a long question, needs the stronger model. An engine
offers "Automatic" only when its cheaper and stronger models are known; for any other engine there
is nothing to choose between. The reader picks "Automatic" in the model drop-down like any model
(it is never the default), and each answer records the model that actually wrote it.
"""

import re

# The model id sent to the engine's registry when the reader picks the option; never sent on to a provider.
AUTO = "auto"
# engine id -> (cheaper model, stronger model), as the engine spells them.
PAIRS: dict[str, tuple[str, str]] = {
    "claude_code": ("haiku", "sonnet"),
    "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5"),
    "openrouter": ("anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"),
    "gemini": ("gemini-3.8-flash", "gemini-4-carbon"),
}
# A question this long (in characters) or longer needs the stronger model.
SHORT_QUESTION_CHARS = 200
# Presets that write something for the reader to send.
_DRAFT_ACTIONS = frozenset({"colleagues", "linkedin", "blog"})
# Verbs that ask for a piece of writing.
_DRAFT_VERB = re.compile(
    r"\b(draft|write|compose|outline|rewrite|rephrase|reword|translate|prepare)\b", re.IGNORECASE)


def offers_auto(engine_id: str) -> bool:
    """Whether the engine has a known cheaper and stronger model."""
    return engine_id in PAIRS


def choose(engine_id: str, action: str | None, content: str) -> str:
    """The model for this turn on `engine_id`: the cheaper one for the Explain preset and for a
    short question without a drafting verb, the stronger one for everything else.

    Raises ValueError for an engine with no known pair.
    """
    if engine_id not in PAIRS:
        raise ValueError(f"{engine_id} has no cheaper and stronger model to choose between")
    cheap, strong = PAIRS[engine_id]
    text = (content or "").strip()
    if action in _DRAFT_ACTIONS or len(text) >= SHORT_QUESTION_CHARS or _DRAFT_VERB.search(text):
        return strong
    if action is None or action == "explain":
        return cheap
    return strong  # the other presets compare an item with the reader's field: they need the reasoning
