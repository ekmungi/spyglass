"""The AcquireResult data shape shared by the acquire ladder's conductor and rungs.

Extracted out of fetch_acquire.py purely to keep that module under the
project's 400-line file cap -- zero behaviour change. `fetch_acquire.py` re-exports
`AcquireResult` from here so every existing `from .fetch_acquire import AcquireResult`
import keeps working unchanged; `fetch_rungs.py` (T2/T3 rung factories) imports it
straight from here, avoiding a fetch_acquire<->fetch_rungs circular import now that
T1 (`_acquire_curl_cffi`) also lives in fetch_rungs.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AcquireResult:
    """The outcome of one acquire() call -- either raw content or a recorded failure.

    Fields:
        payload: the raw content -- bytes today (a T0 httpx response body); later
            tiers may hand back str (e.g. a Jina Reader markdown response) per `kind`.
        kind: what `payload` IS, so the conductor knows whether/how to run an extractor:
            "bytes" (needs a PDF/HTML extractor), "markdown" (already readable text,
            no extraction needed), or "html" (a string of HTML, needs the HTML extractor).
        final_url: the URL actually fetched (after any redirect), used as source_url.
        content_type: the response's content-type header (empty string if unknown).
        tier: which rung of the ladder produced this result (e.g. "T0"); later tasks
            add "T1", "T2", ... as escalation rungs.
        http_status: the HTTP status code, or None when the failure was a transport
            error (connect/timeout) that never reached a response.
        error: a short human-readable failure reason, or None on success.
        ok: True when payload is usable; False on any failure (non-200, transport error).
        encoding: the text charset to decode `payload` bytes with, when `kind` is
            "bytes" and the conductor needs to turn it into a str (e.g. for the HTML
            extractor). httpx resolves this from the response's Content-Type charset
            (falling back to its own charset sniffing), so a declared-charset page
            (e.g. "text/html; charset=iso-8859-1") decodes correctly instead of being
            forced through UTF-8. None when unknown (caller should fall back to
            "utf-8") or when `kind` is not "bytes" (already-decoded rungs don't need
            it). Kept as a plain str, not an httpx object, so non-httpx rungs
            (curl_cffi, etc.) can populate it from their own response without this
            dataclass depending on httpx's types.
        attempts: the full escalation trail -- one (tier, http_status,
            error) tuple per attempt `acquire()` actually made (T0 plus every rung
            tried), in order. A multi-rung give-up would otherwise
            return only the LAST attempted result, dropping the ORIGINAL block
            signal (e.g. the T0 403 that started the escalation) -- the returned
            result always carries the complete trail, so fetch_failure.py can
            compose a legible reason naming every tier tried. Defaulted to `()` so
            every construction without it is unaffected.
    """

    payload: bytes | str
    kind: str
    final_url: str
    content_type: str
    tier: str
    http_status: int | None
    error: str | None
    ok: bool
    encoding: str | None = None
    attempts: tuple[tuple[str, int | None, str | None], ...] = ()
