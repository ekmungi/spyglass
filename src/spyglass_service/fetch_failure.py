"""Compose a structured, card-visible fetch failure from an acquire() attempts trail.

When the acquire ladder gives up, documents.fetch_fulltext must not store a bare
`status="failed"` with only the LAST rung's error: that would silently drop the ORIGINAL
block signal that started the escalation (a 403-at-T0-then-timeout-at-T1 give-up would
read as just "timeout", hiding that the page was actually blocked). This module is the
pure-function home for turning an
AcquireResult.attempts trail into the four structured Content columns (detected_type,
tier_reached, http_status, error_class) plus a single legible `error` string that
names every attempt, so a block reads as "blocked at T0 (HTTP 403); T1 also failed:
Connection reset" and is re-tryable instead of a silent, undifferentiated "failed".

Kept as pure functions (no I/O, no AcquireResult/Content import) so documents.py --
already at its 400-line cap -- only ever CALLS into here; all of the classification
and string-composition logic lives in this one small, independently testable module.
"""

from collections.abc import Sequence

# One attempt entry: (tier, http_status, error) -- mirrors AcquireResult.attempts.
_Attempt = tuple[str, int | None, str | None]

# HTTP statuses that mean "you were blocked" -- mirrors fetch_acquire._BLOCK_STATUSES.
# Duplicated (not imported) to keep this module dependency-free of fetch_acquire, so
# either module can be read/tested in isolation; the two sets must stay in sync if the
# block-status policy ever changes.
_BLOCK_STATUSES = frozenset({403, 429, 503})

# Case-insensitive substrings in an error message that indicate a timeout specifically,
# as opposed to a generic transport failure (connection reset/refused, DNS, TLS).
_TIMEOUT_MARKERS = ("timeout", "timed out")

# The size-cap message fetch_acquire._download_cap_error produces (T0/T1 rungs) --
# matched as a substring so this classifier stays correct if the exact MB figure
# in the message changes.
_SIZE_CAP_MARKER = "exceeds"


def _has_block_status(attempts: Sequence[_Attempt]) -> bool:
    """True when any attempt in the trail carries a block-shaped HTTP status."""
    return any(status in _BLOCK_STATUSES for _tier, status, _error in attempts)


def classify_error_class(attempts: Sequence[_Attempt]) -> str:
    """Classify a give-up into a short, stable bucket -- not the raw exception text.

    Checked in priority order (most specific/actionable signal first):
      1. "blocked" -- ANY attempt in the trail hit a block status (403/429/503). This
         is checked FIRST and across the whole trail (not just the last attempt) so
         the original block classifies the give-up even when a later rung's own
         failure looks like a generic transport error (the T3-debt case).
      2. "size_cap" -- the last attempt's error is the download-size-cap message.
      3. "timeout" -- the last attempt's error mentions a timeout.
      4. "http_error" -- the last attempt reached a real (non-block) HTTP status,
         e.g. 404/410/500: the resource genuinely doesn't exist/errored, not a block.
      5. "transport_error" -- a connect/DNS/TLS failure that never reached a response
         (http_status is None) and isn't a timeout -- the catch-all "never connected"
         bucket.
      6. "empty_extraction" -- no attempts at all (acquire never ran, or produced no
         failure signal) -- used when extraction itself yielded nothing usable rather
         than the fetch failing.

    Args:
        attempts: the acquire() escalation trail, oldest attempt first.

    Returns:
        One of "blocked" / "size_cap" / "timeout" / "http_error" / "transport_error" /
        "empty_extraction".
    """
    if not attempts:
        return "empty_extraction"

    if _has_block_status(attempts):
        return "blocked"

    _last_tier, last_status, last_error = attempts[-1]
    lowered_error = (last_error or "").lower()

    if _SIZE_CAP_MARKER in lowered_error:
        return "size_cap"
    if any(marker in lowered_error for marker in _TIMEOUT_MARKERS):
        return "timeout"
    if last_status is not None:
        # A real HTTP status reached that isn't a block status (checked above) --
        # a genuine failure (404/410/500/...), not a bot-wall.
        return "http_error"
    return "transport_error"


def _pick_http_status(attempts: Sequence[_Attempt]) -> int | None:
    """The most informative status: the FIRST block status in the trail if one
    occurred (the original block, even if a later tier's own status is None/different),
    else the last attempt's status.

    Preferring the original block over the final tier's status matters because the
    last rung is often a transport error (http_status=None) even though the give-up
    chain started with a definitive 403/429/503 -- that original code is the
    actionable signal for a retry decision.
    """
    if not attempts:
        return None
    for _tier, status, _error in attempts:
        if status in _BLOCK_STATUSES:
            return status
    return attempts[-1][1]


def _format_attempt(tier: str, status: int | None, error: str | None) -> str:
    """One attempt's full entry, e.g. "T0 (HTTP 403)" or "T1: Connection reset" when
    there was no HTTP status (a transport error). Used for the LEAD (first) attempt."""
    if status is not None:
        return f"{tier} (HTTP {status})" if error is None else f"{tier} (HTTP {status}): {error}"
    return f"{tier}: {error}" if error else tier


def _describe_later_failure(status: int | None, error: str | None) -> str:
    """The short "what went wrong" fragment for a NON-lead attempt, e.g. "HTTP 403" or
    "Connection reset" -- prefers the error text (more specific) when present, else
    falls back to the bare status."""
    if error:
        return error
    if status is not None:
        return f"HTTP {status}"
    return "no response"


def _compose_reason(attempts: Sequence[_Attempt]) -> str:
    """Build the legible, multi-attempt failure reason from the full trail.

    A single attempt reads as "blocked at T0 (HTTP 403)" (or "failed at T0: <error>"
    for a non-block reason); multiple attempts read as "blocked at T0 (HTTP 403); T1
    also failed: Connection reset; T2 also failed: jina timeout" -- every tier the
    ladder actually tried is named, which is the whole point of this module (never
    lose the earlier tiers' signal to the last rung's error alone).
    """
    if not attempts:
        return "no content extracted"

    lead_tier, lead_status, lead_error = attempts[0]
    verb = "blocked at" if lead_status in _BLOCK_STATUSES else "failed at"
    parts = [f"{verb} {_format_attempt(lead_tier, lead_status, lead_error)}"]

    for tier, status, error in attempts[1:]:
        parts.append(f"{tier} also failed: {_describe_later_failure(status, error)}")

    return "; ".join(parts)


# The 4 structured-failure keys every fetch_fulltext return dict carries,
# defaulted to None -- shared by `finish` (below) so documents.py's every return site
# agrees on the exact key set without repeating it there.
STRUCTURED_FIELDS = ("detected_type", "tier_reached", "http_status", "error_class")


def finish(fetched: dict, **structured: object) -> dict:
    """Merge the 4 structured-failure fields into a `fetched` dict, defaulting any
    field the caller doesn't pass to None.

    Lives here (not documents.py, which is at its 400-line cap) so every
    `fetch_fulltext` return site can stay a one-line wrap instead of expanding each
    dict literal by 4 keys. Pure/dependency-free like the rest of this module.
    """
    return {**fetched, **{key: structured.get(key) for key in STRUCTURED_FIELDS}}


def compose_failure_fields(attempts: Sequence[_Attempt], *, detected_type: str | None) -> dict:
    """Compose the four structured Content columns plus a legible `error` string.

    This is the single entry point documents.fetch_fulltext calls on give-up (and,
    for detected_type/tier_reached only, on success too -- see the module docstring).

    Args:
        attempts: the acquire() escalation trail (AcquireResult.attempts), oldest
            attempt first. `()` when there is no fetch trail at all (e.g. extraction
            ran but produced nothing).
        detected_type: the classified/sniffed content kind (transcript/pdf/image/html)
            or the raw content-type -- passed through unchanged; this module does not
            compute it (that stays the conductor's/content_routing's job).

    Returns:
        {"detected_type", "tier_reached", "http_status", "error_class", "error"}.
        `tier_reached` is the LAST-attempted tier in the trail, or None when `attempts`
        is empty. This is equivalent to the highest tier reached, since acquire()'s
        escalation is monotonic (each attempt only ever moves up the ladder, never back
        down) -- "last" and "highest" are the same tier by construction, not by
        coincidence.
    """
    return {
        "detected_type": detected_type,
        "tier_reached": attempts[-1][0] if attempts else None,
        "http_status": _pick_http_status(attempts),
        "error_class": classify_error_class(attempts),
        "error": _compose_reason(attempts),
    }
