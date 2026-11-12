"""Prompt-cache markers for the API engines that need them.

Anthropic's Messages API and OpenRouter (for Anthropic models) cache a prompt only where the request
says so: a `cache_control` field on a content block caches everything up to and including that
block, for five minutes after each use. Two markers are enough: one on the system prompt (the role,
the reader and the article, identical on every turn) and one on the last message (so the whole
conversation so far is read from the cache on the next turn). Providers that cache by themselves
(OpenAI, Gemini, DeepSeek) need no marker, only a prompt whose beginning does not change, which
`system_split` provides.

Formats checked against the providers' documentation: Anthropic prompt caching
(`cache_control: {"type": "ephemeral"}` on a text block of `system` or of a message) and OpenRouter
prompt caching (the same block inside a message's content array).
"""

from spyglass_service.radar.assist.system_split import split_system

_EPHEMERAL = {"type": "ephemeral"}


def _block(text: str, *, cached: bool) -> dict:
    """One text content block, with the cache marker when `cached`."""
    return {"type": "text", "text": text, **({"cache_control": dict(_EPHEMERAL)} if cached else {})}


def system_blocks(system: str) -> list[dict]:
    """The system prompt as content blocks: the stable part marked for caching, then the part that
    changes on every turn (the items retrieved for a question about the feed), unmarked."""
    stable, varying = split_system(system)
    if not stable.strip():
        return [_block(varying, cached=False)] if varying else []
    blocks = [_block(stable, cached=True)]
    if varying:
        blocks.append(_block(varying, cached=False))
    return blocks


def mark_last_message(messages: list[dict]) -> list[dict]:
    """A copy of `messages` whose last message is a content block marked for caching.

    An empty last message cannot carry a marker (the API refuses empty text blocks) and is left alone.
    """
    if not messages or not messages[-1].get("content"):
        return list(messages)
    last = messages[-1]
    return [*messages[:-1], {**last, "content": [_block(str(last["content"]), cached=True)]}]
