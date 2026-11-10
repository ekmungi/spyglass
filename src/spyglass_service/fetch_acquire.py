"""The acquire layer: fetches raw content for a URL, escalating through tiers.

This is the home for the acquisition ladder: T0 is a plain httpx GET; T1 (curl_cffi
TLS/JA3 impersonation) is the first escalation rung, so a T0
response that looks like a bot-wall (403/429/503, a transport error, or a challenge
page in a 200 body) is retried through curl_cffi before giving up. The T2 rung
(Jina Reader, a hosted renderer that clears JS-gated/bot-walled pages server-side and
returns already-extracted markdown) is added by `build_rungs`, a Settings-driven ladder
builder -- the Jina rung is included only when `settings.jina_enabled` is True. The
T3 rung (patchright, a local headless-Chromium stealth renderer) is the
last-resort local tier -- unlike Jina it is HTML-ONLY: `build_rungs` includes it only
when `settings.browser_enabled` AND the target kind is "html", so a PDF/image ladder
never launches a browser. Escalation is encapsulated entirely inside `acquire()` -- the
conductor (documents.fetch_fulltext) and its callers never need to change when a rung
is added. Per-kind rung selection can be refined further behind the same
AcquireResult shape.

The T2/T3 rung factories and the `build_rungs` ladder assembler live in
`fetch_rungs.py` (split out purely to keep this file under the project's
400-line cap) -- this module keeps T0/T1 and `acquire()` itself, the actual
escalation conductor. `AcquireResult` itself lives in `fetch_types.py` (same
reason) and is re-exported below so every existing import is unaffected.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace

import httpx

from .fetch_types import AcquireResult

__all__ = ["AcquireResult", "acquire"]

# Case-insensitive substrings that show up in a bot-challenge interstitial page (a 200
# response whose body is NOT the real content, e.g. Cloudflare's "Just a moment..." or
# a DataDome/other WAF captcha wall). Their presence in an otherwise-200 body is treated
# as a block, not a success, so acquire() escalates instead of handing back challenge
# HTML as if it were the article.
_CHALLENGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "challenge-platform",
    "/cdn-cgi/challenge",
    "datadome",
    "captcha-delivery",
)

# HTTP statuses that typically mean "you were blocked", not "this doesn't exist" --
# worth retrying via a rung with a different fetch strategy (e.g. curl_cffi's TLS
# impersonation). Deliberately narrow: 404/410/500 etc. are real failures no amount of
# impersonation fixes, so they are excluded and fall through as the T0 result.
_BLOCK_STATUSES = frozenset({403, 429, 503})

# Default cap on a single raw-bytes download (T0/T1 rungs only -- Jina/browser rungs
# return already-extracted text, never raw file bytes, so they don't need this guard).
# Bounds worst-case memory for a mislabeled/giant file (e.g. a URL that looks like an
# article but is actually a multi-GB video); ~25MB comfortably covers any real
# PDF/HTML article while stopping a runaway download cold. Exposed as a parameter
# (not hardcoded into the fetch calls) so it can become a Settings-driven value later
# without changing either rung's signature again, and so tests can inject a tiny
# max_bytes instead of allocating a real 25MB body.
_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def _is_blocked(result: AcquireResult) -> bool:
    """True when `result` looks like a bot-wall block worth retrying via another rung.

    Three signals, all narrow on purpose (a false positive wastes a rung; a false
    negative just means no escalation, which is the T0-only behaviour):
      - a block-shaped HTTP status (403/429/503) -- typical WAF/anti-bot response codes.
      - a transport error (`not ok` and `http_status is None`) -- never got a response
        at all (connection reset, TLS handshake failure), which curl_cffi's different
        TLS fingerprint can sometimes get past.
      - a 200 response whose body is actually a challenge interstitial (Cloudflare,
        DataDome, etc.) rather than the real page -- checked as a case-insensitive
        substring match against `_CHALLENGE_MARKERS`.

    Genuine failures (404/410/500/...) return False: no rung's fetch STRATEGY changes
    whether the resource exists, so escalating would just waste a round trip.
    """
    if result.http_status in _BLOCK_STATUSES:
        return True
    if not result.ok and result.http_status is None:
        return True
    if result.ok and result.http_status == 200:
        body = result.payload
        text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
        lowered = text.lower()
        return any(marker in lowered for marker in _CHALLENGE_MARKERS)
    return False


def _download_cap_error(max_bytes: int) -> str:
    """The shared legible failure message for both rungs' size-cap abort -- kept as
    one string builder so T0/T1 report the cap consistently."""
    return f"download exceeds {max_bytes // (1024 * 1024)}MB cap"


def _acquire_httpx(
    url: str, *, client: httpx.Client, max_bytes: int = _MAX_DOWNLOAD_BYTES
) -> AcquireResult:
    """T0 rung: a plain httpx GET, streamed under a size cap. HTTP errors and
    non-200s are captured into the result (ok=False + error/http_status) rather than
    raised -- callers treat fetch failure as data, not a crash (mirrors the original
    fetch_fulltext contract).

    Streams via `client.stream()` instead of `client.get()` so a mislabeled/giant
    file can't balloon memory: `Content-Length` (when present) is checked BEFORE any
    body bytes are read, so an honestly-huge response aborts without transferring a
    byte; the accumulated body is also checked after every chunk, aborting the moment
    it exceeds `max_bytes` even when Content-Length lies or is absent entirely (a
    header-only check can't catch either case). `max_bytes` defaults to the module
    cap but is a parameter so tests can inject a low value instead of allocating a
    real ~25MB body. `httpx.MockTransport` supports `.stream()` the same as `.get()`,
    so this is a behaviour-preserving swap for every existing small-body test.

    The `status_code != 200` check runs BEFORE the Content-Length cap pre-check --
    a non-200 response (e.g. a 500 error page) that happens to declare an oversized
    Content-Length must report `"HTTP 500"`, not the cap message, since the status is
    the more informative failure and matches the structured-failure theme elsewhere in
    this module. The cap pre-check only applies once the response is confirmed 200.
    """
    try:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                return AcquireResult(
                    payload=b"", kind="bytes", final_url=str(response.url),
                    content_type="", tier="T0", http_status=response.status_code,
                    error=f"HTTP {response.status_code}", ok=False,
                )

            content_length = response.headers.get("content-length")
            if content_length is not None and content_length.isdigit():
                if int(content_length) > max_bytes:
                    return AcquireResult(
                        payload=b"", kind="bytes", final_url=str(response.url),
                        content_type="", tier="T0", http_status=response.status_code,
                        error=_download_cap_error(max_bytes), ok=False,
                    )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    return AcquireResult(
                        payload=b"", kind="bytes", final_url=str(response.url),
                        content_type="", tier="T0", http_status=response.status_code,
                        error=_download_cap_error(max_bytes), ok=False,
                    )
                chunks.append(chunk)

            return AcquireResult(
                payload=b"".join(chunks),
                kind="bytes",
                final_url=str(response.url),
                content_type=response.headers.get("content-type", ""),
                tier="T0",
                http_status=response.status_code,
                error=None,
                ok=True,
                # httpx.Response.encoding resolves the declared Content-Type charset
                # (falling back to its own sniffing/default) -- the same resolution
                # `.text` uses internally, so decoding `payload` with this later
                # reproduces `.text` exactly. Reading it here (post iter_bytes, inside
                # the `with` block) mirrors how `.get()` resolves it after `.content`.
                encoding=response.encoding,
            )
    except httpx.HTTPError as error:
        return AcquireResult(
            payload=b"", kind="bytes", final_url=url, content_type="", tier="T0",
            http_status=None, error=str(error), ok=False,
        )


def _acquire_curl_cffi(url: str, *, max_bytes: int = _MAX_DOWNLOAD_BYTES) -> AcquireResult:
    """T1 rung: fetch via curl_cffi, impersonating a real Chrome TLS/JA3 fingerprint.

    Many bot-walls key off the TLS handshake shape (JA3), not just headers -- httpx's
    plain TLS stack gets blocked where a browser-shaped handshake sails through.
    curl_cffi is imported lazily (inside this function, not at module top) so the real
    library only loads in production; unrelated unit tests never pay its import cost
    or trip any of its import-time warnings under this project's `filterwarnings =
    ["error"]` pytest setting (mirrors the trafilatura/pypdf lazy-import pattern used
    elsewhere in this codebase).

    Content-type-agnostic: this rung just returns whatever bytes curl_cffi got, same
    as T0 -- per-content-type branching (PDF/image/etc.) is the conductor's job
    (documents.fetch_fulltext), not this rung's.

    Size cap is BEST-EFFORT here, unlike T0's true streaming: curl_cffi's `.get()`
    buffers the whole response body internally before this function ever sees it, so
    there is no true streaming hook available through this call shape to abort
    mid-transfer. The guard is therefore two checks after the fact -- a
    Content-Length pre-check (same as T0, catches an honestly-declared oversized
    response before doing anything with `.content`) and a post-fetch `len(content)`
    check (catches a lying/absent Content-Length, after the transfer already
    happened). This still stops an oversized body from propagating further into the
    pipeline (extraction, storage) and gives the same legible failure shape as T0 --
    it just can't prevent curl_cffi's own memory use during the fetch itself. T1 only
    runs when T0 was blocked (see `acquire()`), so this path is rare in practice.
    """
    try:
        from curl_cffi import requests as curl_requests

        response = curl_requests.get(url, impersonate="chrome", timeout=60)
    except Exception as error:  # curl_cffi raises its own error hierarchy; a rung
        # failure must be data (like the T0 path), never a crash that takes down acquire().
        return AcquireResult(
            payload=b"", kind="bytes", final_url=url, content_type="", tier="T1",
            http_status=None, error=str(error), ok=False,
        )

    content_length = response.headers.get("content-length")
    if content_length is not None and str(content_length).isdigit():
        if int(content_length) > max_bytes:
            return AcquireResult(
                payload=b"", kind="bytes", final_url=str(response.url), content_type="",
                tier="T1", http_status=response.status_code,
                error=_download_cap_error(max_bytes), ok=False,
            )

    if response.status_code != 200:
        return AcquireResult(
            payload=b"", kind="bytes", final_url=str(response.url), content_type="",
            tier="T1", http_status=response.status_code,
            error=f"HTTP {response.status_code}", ok=False,
        )

    if len(response.content) > max_bytes:
        return AcquireResult(
            payload=b"", kind="bytes", final_url=str(response.url), content_type="",
            tier="T1", http_status=response.status_code,
            error=_download_cap_error(max_bytes), ok=False,
        )

    return AcquireResult(
        payload=response.content,
        kind="bytes",
        final_url=str(response.url),
        content_type=response.headers.get("content-type", ""),
        tier="T1",
        http_status=response.status_code,
        error=None,
        ok=True,
        # curl_cffi's Response.encoding mirrors requests' -- resolved from the
        # Content-Type charset when declared, else None (caller falls back to utf-8).
        encoding=getattr(response, "encoding", None),
    )


# Declared tier tag (see `acquire()`'s start_tier docstring): `acquire()` reads this
# attribute -- when present -- to compute a rung's ordinal for the start_tier skip,
# rather than relying on the rung's POSITION in the `rungs` list. This one is a plain
# function, so the tag is set as a module-level attribute right after the def; the T2/T3
# rung factories in fetch_rungs.py set the same attribute on the closures they return.
_acquire_curl_cffi.tier = "T1"

# The production escalation ladder used when `acquire()` is called without an explicit
# `rungs` override. Appending a rung here (patchright, ...) is the only change later
# tasks need to make in this module -- `acquire()`'s loop and every existing
# caller/test that pins its own `rungs` list are unaffected. Note: this tuple is the
# curl-only fallback used when the caller has no Settings at all (see
# documents.fetch_fulltext's rung-precedence rule); the Settings-aware ladder is
# `build_rungs` (fetch_rungs.py), which also conditionally includes the Jina/browser
# rungs.
_DEFAULT_RUNGS: tuple[Callable[[str], AcquireResult], ...] = (_acquire_curl_cffi,)

# Ordinal position of each tier on the "T0".."T3" scale, used only to compare a
# `start_tier` against an attempt's position in the sequence (T0 is always the httpx
# GET; each rung after it is one tier higher, in ladder order). A plain string
# comparison ("T10" < "T2") would be wrong once tiers hit double digits, so
# `start_tier` skip logic always goes through this ordinal instead of comparing the
# "T#" strings directly.
_TIER_ORDER = ("T0", "T1", "T2", "T3")


def _tier_ordinal(tier: str) -> int:
    """The position of `tier` on the "T0".."T3" scale (0 for T0, 1 for T1, ...).

    Only used to compare tiers numerically (see `_TIER_ORDER`). An unrecognized tier
    (a tier above T3, or a typo) sorts after every known tier rather than raising, so a
    forward-compatible rung never crashes acquire() -- it is simply never skipped.
    """
    return _TIER_ORDER.index(tier) if tier in _TIER_ORDER else len(_TIER_ORDER)


def acquire(
    url: str,
    *,
    client: httpx.Client,
    target_kind: str = "html",
    rungs: Sequence[Callable[[str], AcquireResult]] | None = None,
    start_tier: str | None = None,
) -> AcquireResult:
    """Fetch `url`, escalating through tiers when the current tier looks blocked.

    Runs T0 (a plain httpx GET) first. If the T0 result is not blocked (`_is_blocked`
    is False) -- including a clean 200 or a genuine non-block failure like 404 -- it is
    returned immediately, no escalation attempted. If T0 IS blocked, each rung in
    `rungs` (in order) is tried in turn; the first rung result that is both `ok` and
    not itself blocked wins. If every rung fails or is still blocked, the LAST rung's
    result is returned (the most escalated attempt is the most informative failure to
    surface) -- or the T0 result itself if `rungs` is empty.

    `rungs` defaults to the real production ladder (currently just curl_cffi, T1) when
    omitted (None). Tests and other callers that need determinism/offline behaviour
    pass their own list -- `rungs=[]` pins T0-only (a block is returned as-is), or a list
    of fake rung callables to drive escalation without real network. This keeps the seam
    stable as the production ladder grows: a caller that already pins `rungs=[]` or a stub
    list never needs to change.

    `target_kind` (the kind of content the caller ultimately wants, e.g. "html" vs
    "markdown") is accepted so the signature is stable for later tasks, but is not yet
    used to branch behaviour -- T1 (curl_cffi) is content-type-agnostic.

    `start_tier` lets a caller that already knows a domain's
    last-winning tier (fetch_cache.get_cached_tier) skip every attempt BELOW that tier
    instead of re-proving each lower one fails again. Each rung's ordinal is read from
    its DECLARED `.tier` attribute (set by the rung factory -- `_acquire_curl_cffi.tier
    = "T1"`, `make_jina_rung(...)` returns a closure tagged "T2", `make_browser_rung(...)`
    tagged "T3"), NOT from its position in `rungs`. This matters because `build_rungs`
    produces a PARTIAL ladder -- the Jina/browser rungs are omitted when disabled or
    (for browser) when `target_kind != "html"` -- so `rungs` can be e.g. [curl_T1,
    browser_T3] with no T2 present at all; position would then silently misidentify
    browser_T3 as "the T2 rung". A rung with no declared tier (a bare test stub) falls
    back to the old positional guess (`position + 1`) so ad-hoc stubs without `.tier`
    set still behave sanely. When `start_tier` is None or "T0" (the default), every
    attempt runs -- today's behaviour, unchanged. Escalation past `start_tier` on
    failure proceeds exactly as usual (first ok+unblocked wins, else the last attempted
    result) -- this only ever skips forward, never back down to a tier already known to
    fail, and a rung below `start_tier` is genuinely never called (not just ignored).

    Every attempt actually made is recorded into an `attempts` trail --
    see `AcquireResult.attempts` -- so the returned result never loses an earlier
    tier's info even though only one AcquireResult object comes back.
    """
    active_rungs = _DEFAULT_RUNGS if rungs is None else rungs
    start_ordinal = _tier_ordinal(start_tier) if start_tier else 0

    # One (tier, http_status, error) entry per attempt actually made -- see AcquireResult.attempts.
    attempts: list[tuple[str, int | None, str | None]] = []

    result = None
    if start_ordinal <= _tier_ordinal("T0"):
        result = _acquire_httpx(url, client=client)
        attempts.append((result.tier, result.http_status, result.error))
        if not _is_blocked(result):
            return _with_attempts(result, attempts)

    # Prefer each rung's DECLARED tier (set by the rung factory) to compute its
    # ordinal; only fall back to the positional guess when a rung has no `.tier` set
    # (a bare test stub) -- see the start_tier docstring above for why position alone
    # is wrong once `rungs` can be a partial ladder with gaps.
    for position, rung in enumerate(active_rungs):
        declared_tier = getattr(rung, "tier", None)
        rung_ordinal = _tier_ordinal(declared_tier) if declared_tier else position + 1
        if rung_ordinal < start_ordinal:
            continue
        result = rung(url)
        attempts.append((result.tier, result.http_status, result.error))
        if result.ok and not _is_blocked(result):
            return _with_attempts(result, attempts)

    if result is None:
        # start_tier skipped T0 AND every rung's declared tier is below it too (e.g.
        # start_tier="T3" with only a T1 rung available, or a partial ladder that
        # omits the rung at/above start_tier entirely) -- nothing was ever attempted.
        # Fall back to running T0 anyway rather than returning None, so acquire()
        # always returns an AcquireResult; this is the defensive edge for a cached
        # tier whose rung a Settings change (e.g. disabling Jina) has since removed
        # from the ladder.
        result = _acquire_httpx(url, client=client)
        attempts.append((result.tier, result.http_status, result.error))

    return _with_attempts(result, attempts)


def _with_attempts(
    result: AcquireResult, attempts: list[tuple[str, int | None, str | None]]
) -> AcquireResult:
    """Re-stamp `result` with the accumulated `attempts` trail (frozen dataclass, so
    via `dataclasses.replace` rather than mutation)."""
    return replace(result, attempts=tuple(attempts))
