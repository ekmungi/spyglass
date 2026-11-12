"""Split an assistant system prompt into the part that stays the same and the part that does not.

A conversation about one item or one day has a system prompt that is the same on every turn: the
role, the reader, the item's text. A conversation about the whole feed adds, on every turn, the items
retrieved for that question (and today's date). Providers read a prompt from their cache only up to the
first character that differs from the last request, so everything that varies has to come after
everything that does not. Engines call `split_system` and send the first part as the system prompt
(marked for caching) and the second part with the reader's message.
"""

# The line that opens the retrieved items of a feed conversation (see `assist.feed_context`).
FEED_MARKER = "=== THE FEED ==="
# The tag the privacy layer wraps around material (see `radar.privacy`).
_FENCE_OPEN = "<spyglass_material>"


def split_system(system: str) -> tuple[str, str]:
    """(stable, varying): the system prompt up to the retrieved feed items, and the items.

    A prompt without a feed section is entirely stable, so the second part is "". The fence the
    privacy layer put around the feed section goes with the varying part.
    """
    at = system.find(FEED_MARKER)
    if at < 0:
        return system, ""
    fence = system.rfind(_FENCE_OPEN, 0, at)
    cut = fence if fence >= 0 else at
    return system[:cut].rstrip(), system[cut:]
