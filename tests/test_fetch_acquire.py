"""Tests for the acquire layer -- the ladder home for the fetch pipeline.

``acquire()`` starts with a single httpx GET (T0); a T0 block (403/429/503, a transport
error, or a bot-challenge body) escalates to the next rung, which in the default ladder is
curl_cffi (T1). Escalation is driven by an injectable `rungs` sequence, so
callers/tests that pin `rungs=[]` (T0-only) or a stub list never need editing as the
ladder grows. The Settings-driven rung factories (Jina T2, browser T3) and the
`build_rungs` ladder assembler have their own tests in test_fetch_rungs.py
(mirroring the fetch_acquire.py/fetch_rungs.py module split).
"""

import httpx

from spyglass_service.fetch_acquire import (
    AcquireResult,
    _acquire_httpx,
    _is_blocked,
    acquire,
)


def client_for(handler) -> httpx.Client:
    """An httpx client wired to a MockTransport handler (no real network)."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_curl_result(url: str = "https://example.test/a") -> AcquireResult:
    """A stand-in successful T1 (curl_cffi) result for injecting as a fake rung."""
    return AcquireResult(
        payload=b"<p>via curl_cffi</p>", kind="bytes", final_url=url,
        content_type="text/html", tier="T1", http_status=200, error=None, ok=True,
        encoding="utf-8",
    )


def _failed_curl_result(url: str = "https://example.test/a") -> AcquireResult:
    """A stand-in failed T1 (curl_cffi) result for injecting as a fake rung."""
    return AcquireResult(
        payload=b"", kind="bytes", final_url=url, content_type="", tier="T1",
        http_status=403, error="HTTP 403", ok=False,
    )


def test_acquire_returns_bytes_payload_on_200() -> None:
    """A 200 response wraps into an ok AcquireResult with the raw bytes and tier T0."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client)

    assert isinstance(result, AcquireResult)
    assert result.ok is True
    assert result.payload == b"<p>hi</p>"
    assert result.kind == "bytes"
    assert result.tier == "T0"
    assert result.http_status == 200
    assert result.final_url == "https://example.test/a"
    assert "html" in result.content_type
    assert result.error is None


def test_acquire_accepts_target_kind_kwarg() -> None:
    """target_kind is accepted (unused branching yet) so the signature is stable for later tasks."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, target_kind="markdown")

    assert result.ok is True


def test_acquire_marks_non_200_as_failed() -> None:
    """A non-200 response is NOT raised -- it comes back as ok=False with the status recorded.

    Pins rungs=[] (T0-only) so a 403 -- a block signal -- does not escalate to the
    real (network-touching) production ladder in this unit test.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with client_for(handler) as client:
        result = acquire("https://example.test/paywalled", client=client, rungs=[])

    assert result.ok is False
    assert result.http_status == 403
    assert result.error is not None
    assert "403" in result.error
    assert result.tier == "T0"


def test_acquire_marks_connect_error_as_failed() -> None:
    """A transport-level error (reset/timeout) is recorded, never raised. rungs=[] keeps
    this offline (see test_acquire_marks_non_200_as_failed)."""
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("forcibly closed by the remote host")

    with client_for(handler) as client:
        result = acquire("https://example.test/x", client=client, rungs=[])

    assert result.ok is False
    assert result.http_status is None
    assert "forcibly closed" in (result.error or "")
    assert result.tier == "T0"


# -- Escalation: T0 block -> T1 (curl_cffi), via the injectable `rungs` seam ------


def test_acquire_escalates_to_rung_on_403() -> None:
    """A T0 403 is a block signal -- the injected rung runs and its success wins."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    calls: list[str] = []

    def fake_rung(url: str) -> AcquireResult:
        calls.append(url)
        return _ok_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[fake_rung])

    assert calls == ["https://example.test/a"]
    assert result.ok is True
    assert result.tier == "T1"
    assert result.payload == b"<p>via curl_cffi</p>"


def test_acquire_escalates_to_rung_on_transport_error() -> None:
    """A T0 transport error (no response at all) also escalates to the next rung."""
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("forcibly closed by the remote host")

    calls: list[str] = []

    def fake_rung(url: str) -> AcquireResult:
        calls.append(url)
        return _ok_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/x", client=client, rungs=[fake_rung])

    assert calls == ["https://example.test/x"]
    assert result.ok is True
    assert result.tier == "T1"


def test_acquire_escalates_on_challenge_marker_in_200_body() -> None:
    """A 200 response whose body is a bot-challenge page is treated as blocked."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"},
            content=b"<html><body>Just a moment...</body></html>",
        )

    calls: list[str] = []

    def fake_rung(url: str) -> AcquireResult:
        calls.append(url)
        return _ok_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[fake_rung])

    assert calls == ["https://example.test/a"]
    assert result.ok is True
    assert result.tier == "T1"


def test_acquire_clean_200_never_calls_rung() -> None:
    """A clean T0 200 returns immediately -- no escalation, no rung call."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    calls: list[str] = []

    def fake_rung(url: str) -> AcquireResult:
        calls.append(url)
        return _ok_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[fake_rung])

    assert calls == []
    assert result.ok is True
    assert result.tier == "T0"


def test_acquire_404_never_calls_rung() -> None:
    """A genuine 404 is NOT a block signal -- curl_cffi would not fix it, so no escalation."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    calls: list[str] = []

    def fake_rung(url: str) -> AcquireResult:
        calls.append(url)
        return _ok_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/missing", client=client, rungs=[fake_rung])

    assert calls == []
    assert result.ok is False
    assert result.tier == "T0"
    assert result.http_status == 404


def test_acquire_returns_rung_failure_when_both_tiers_fail() -> None:
    """T0 blocked AND the next rung also fails -- return the failure, tier reflects T1."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    def fake_rung(url: str) -> AcquireResult:
        return _failed_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[fake_rung])

    assert result.ok is False
    assert result.tier == "T1"
    assert result.error is not None


def test_acquire_empty_rungs_never_escalates_even_when_blocked() -> None:
    """rungs=[] means T0-only: a block signal is returned as-is, no escalation attempted.

    This is the seam test_documents.py's block-path tests rely on to stay offline and
    stable as later tasks lengthen the production rung list.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[])

    assert result.ok is False
    assert result.tier == "T0"
    assert result.http_status == 429


def test_acquire_rungs_defaults_to_the_real_production_ladder() -> None:
    """Omitting `rungs` (None) means "use the real production rungs" -- existing callers
    that pass neither `rungs` nor `curl_fetcher` are unaffected on the success path,
    where no rung is ever invoked."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client)

    assert result.ok is True
    assert result.tier == "T0"


# -- start_tier: skip attempts below a cached tier -------
#
# `start_tier` lets a caller that already knows a domain's winning tier (from
# fetch_cache.get_cached_tier) skip straight past the lower rungs that domain is
# known to fail -- the T0 client is never invoked at all when start_tier is above T0,
# and any rung whose own tier sits below start_tier is skipped too. Escalation past
# start_tier on failure still proceeds exactly as today (first ok+unblocked wins, else
# the last attempted result), so a regression at the cached tier still climbs further.


def test_acquire_start_tier_t2_skips_t0_and_t1_client_never_called() -> None:
    """start_tier="T2" must not touch the T0 httpx client at all -- assert via a
    handler that raises if ever invoked -- and skips a T1-tagged rung too, landing
    directly on the first rung whose tier is >= T2."""
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("T0 must not be attempted when start_tier is above T0")

    def t1_rung(_url: str) -> AcquireResult:
        raise AssertionError("a T1 rung must be skipped when start_tier is T2")

    def t2_rung(url: str) -> AcquireResult:
        return AcquireResult(
            payload="via jina", kind="markdown", final_url=url, content_type="text/markdown",
            tier="T2", http_status=200, error=None, ok=True,
        )

    with client_for(handler) as client:
        result = acquire(
            "https://example.test/a", client=client,
            rungs=[t1_rung, t2_rung], start_tier="T2",
        )

    assert result.ok is True
    assert result.tier == "T2"
    assert result.payload == "via jina"


def test_acquire_start_tier_none_runs_the_full_ladder() -> None:
    """start_tier=None (the default) is identical to today's behaviour: T0 runs first."""
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("t0")
        return httpx.Response(200, content=b"data")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, start_tier=None)

    assert calls == ["t0"]
    assert result.ok is True
    assert result.tier == "T0"


def test_acquire_start_tier_t0_runs_the_full_ladder() -> None:
    """start_tier="T0" is explicitly the same as omitting it -- T0 still runs."""
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("t0")
        return httpx.Response(200, content=b"data")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, start_tier="T0")

    assert calls == ["t0"]
    assert result.ok is True
    assert result.tier == "T0"


def test_acquire_start_tier_regression_escalates_further_up(monkeypatch) -> None:
    """A cached T2 domain that now FAILS at T2 escalates further up (to a T3 rung),
    never falling back down to T0/T1 -- matches the "go up, never down" contract.

    Uses call-recording spies (not just return values) so the assertions prove the
    REAL retry-at-cached-tier path: a T1 rung below start_tier is never invoked at
    all (the skip is real, not accidental), the T2 rung IS invoked and fails (the
    cached tier is genuinely retried, not skipped over), and only then does T3 run
    and win. Each rung's `.tier` is the DECLARED tier acquire() must read -- ladder
    POSITION here (0, 1, 2) does not match tier ordinal (1, 2, 3), so a positional
    reader would misidentify which rung is "the T2 rung" and this test would pass
    for the wrong reason (see `acquire()`'s start_tier docstring in fetch_acquire.py)."""
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("T0 must not be attempted when start_tier is T2")

    def t1_rung(url: str) -> AcquireResult:
        calls.append("t1")
        raise AssertionError("a T1 rung must be skipped when start_tier is T2")

    t1_rung.tier = "T1"

    def t2_rung(url: str) -> AcquireResult:
        calls.append("t2")
        return AcquireResult(
            payload="", kind="markdown", final_url=url, content_type="",
            tier="T2", http_status=403, error="HTTP 403", ok=False,
        )

    t2_rung.tier = "T2"

    def t3_rung(url: str) -> AcquireResult:
        calls.append("t3")
        return AcquireResult(
            payload="<p>rendered</p>", kind="html", final_url=url, content_type="text/html",
            tier="T3", http_status=200, error=None, ok=True,
        )

    t3_rung.tier = "T3"

    with client_for(handler) as client:
        result = acquire(
            "https://example.test/a", client=client,
            rungs=[t1_rung, t2_rung, t3_rung], start_tier="T2",
        )

    # Proves the skip (T1 never called), the retry-at-cached-tier (T2 called and
    # failed), and the escalation (T3 called and won) -- in that order.
    assert calls == ["t2", "t3"]
    assert result.ok is True
    assert result.tier == "T3"


def test_acquire_start_tier_partial_ladder_skips_by_declared_tier_not_position() -> None:
    """A partial ladder (Jina AND curl both omitted -- e.g. browser is the only rung
    left) must skip/run by DECLARED tier, not position: rungs=[T3-only] with
    start_tier="T2" must RUN that rung -- its declared tier (T3) is >= T2 -- even
    though it sits at list position 0, the position a T1 rung would occupy in a full
    ladder. A positional reader computes ordinal = position+1 = 1 (T1), which is
    BELOW start_tier "T2" (ordinal 2), so it would wrongly SKIP this rung entirely
    and fall through to the T0-fallback edge instead of ever calling it -- the
    opposite of what a "T3 rung available" ladder should do. This is the concrete
    shape of the reported bug: `build_rungs("html")` with jina disabled produces
    `[curl_T1, browser_T3]`; trimming further (as here) isolates just the mismatch."""
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("T0 must not be attempted -- a T3 rung is available")

    def t3_rung(url: str) -> AcquireResult:
        calls.append("t3")
        return AcquireResult(
            payload="<p>rendered</p>", kind="html", final_url=url, content_type="text/html",
            tier="T3", http_status=200, error=None, ok=True,
        )

    t3_rung.tier = "T3"

    with client_for(handler) as client:
        result = acquire(
            "https://example.test/a", client=client,
            rungs=[t3_rung], start_tier="T2",
        )

    assert calls == ["t3"]
    assert result.ok is True
    assert result.tier == "T3"


def test_acquire_start_tier_above_every_rung_falls_back_to_t0() -> None:
    """When start_tier is above every declared tier in a partial ladder (nothing
    eligible to attempt), acquire() falls back to running T0 rather than returning
    None -- the defensive edge for a cached tier whose rung a Settings change has
    since removed from the ladder."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"t0 fallback")

    def t1_rung(_url: str) -> AcquireResult:
        raise AssertionError("a T1 rung must be skipped when start_tier is T3")

    t1_rung.tier = "T1"

    with client_for(handler) as client:
        result = acquire(
            "https://example.test/a", client=client,
            rungs=[t1_rung], start_tier="T3",
        )

    assert result.ok is True
    assert result.tier == "T0"
    assert result.payload == b"t0 fallback"


def test_acquire_start_tier_skips_rungs_strictly_below_only() -> None:
    """A rung whose tier equals start_tier is INCLUDED (>= start_tier), only rungs
    strictly below are skipped."""
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("T0 must not be attempted when start_tier is T1")

    def t1_rung(url: str) -> AcquireResult:
        calls.append("t1")
        return AcquireResult(
            payload=b"via curl", kind="bytes", final_url=url, content_type="text/html",
            tier="T1", http_status=200, error=None, ok=True,
        )

    with client_for(handler) as client:
        result = acquire(
            "https://example.test/a", client=client, rungs=[t1_rung], start_tier="T1",
        )

    assert calls == ["t1"]
    assert result.ok is True
    assert result.tier == "T1"


# -- _is_blocked branch table -----------------------------------------------------


def _result(*, ok: bool, http_status: int | None, payload: bytes = b"") -> AcquireResult:
    """Minimal AcquireResult builder for exercising _is_blocked in isolation."""
    return AcquireResult(
        payload=payload, kind="bytes", final_url="https://example.test/a",
        content_type="text/html", tier="T0", http_status=http_status,
        error=None if ok else "err", ok=ok,
    )


def test_is_blocked_true_for_403_429_503() -> None:
    """403/429/503 are treated as block signals regardless of the ok flag."""
    for status in (403, 429, 503):
        assert _is_blocked(_result(ok=False, http_status=status)) is True


def test_is_blocked_true_for_transport_error() -> None:
    """not ok with no http_status at all (a transport error) is a block signal."""
    assert _is_blocked(_result(ok=False, http_status=None)) is True


def test_is_blocked_true_for_challenge_marker_in_200_body() -> None:
    """Each known bot-challenge marker in an ok 200 body is detected, case-insensitively."""
    markers = [
        "just a moment", "cf-browser-verification", "challenge-platform",
        "/cdn-cgi/challenge", "datadome", "captcha-delivery",
    ]
    for marker in markers:
        body = f"<html>{marker.upper()}</html>".encode()
        assert _is_blocked(_result(ok=True, http_status=200, payload=body)) is True


def test_is_blocked_false_for_clean_200() -> None:
    """A normal 200 body with no challenge marker is not blocked."""
    assert _is_blocked(_result(ok=True, http_status=200, payload=b"<p>hello world</p>")) is False


def test_is_blocked_false_for_genuine_failures() -> None:
    """404/410/500 are real failures curl_cffi cannot fix -- not block signals."""
    for status in (404, 410, 500):
        assert _is_blocked(_result(ok=False, http_status=status)) is False


# -- Download size cap ------------------------------------
#
# The cap protects the byte-returning rungs (T0 httpx, T1 curl_cffi) from a
# mislabeled/giant file ballooning memory. T0 gets a TRUE streaming cap (aborts
# mid-read the moment the accumulated body exceeds max_bytes, defending a lying
# or absent Content-Length); T1 is best-effort (curl_cffi buffers internally, so
# it can only pre-check Content-Length and post-check the fetched length). Tests
# inject a LOW max_bytes (never the real ~25MB constant) so no test allocates a
# large body -- the abort logic is exercised with tiny payloads.


def test_acquire_httpx_content_length_precheck_aborts_before_reading_body() -> None:
    """A declared Content-Length over max_bytes aborts immediately -- ok=False, a
    legible error mentioning the cap, tier T0. The body is never streamed/read."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream", "content-length": "1000"},
            content=b"x" * 1000,
        )

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/huge", client=client, max_bytes=100)

    assert result.ok is False
    assert result.tier == "T0"
    assert result.error is not None
    assert "cap" in result.error.lower()


def test_acquire_httpx_non_200_with_oversized_content_length_reports_http_status() -> None:
    """A non-200 response (e.g. a 500 error page) that happens to declare an oversized
    Content-Length must report the HTTP status, not the size cap -- the status check
    runs first, so the cap pre-check never even looks at this response's headers."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            headers={"content-type": "text/html", "content-length": "999999999"},
            content=b"<html>error page</html>",
        )

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/broken", client=client, max_bytes=100)

    assert result.ok is False
    assert result.tier == "T0"
    assert result.http_status == 500
    assert result.error == "HTTP 500"
    assert "cap" not in (result.error or "").lower()


def test_acquire_httpx_streams_abort_when_content_length_lies_or_is_absent() -> None:
    """No/absent Content-Length but a body bigger than a LOW injected max_bytes --
    aborts mid-stream (not OOM/hang), a legible failure, never raises."""
    def handler(_request: httpx.Request) -> httpx.Response:
        # No content-length header declared -- httpx's MockTransport still lets the
        # body stream in chunks via iter_bytes(), so the mid-stream guard is what
        # has to catch this, not the pre-check.
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"y" * 500
        )

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/lying", client=client, max_bytes=100)

    assert result.ok is False
    assert result.tier == "T0"
    assert result.error is not None
    assert "cap" in result.error.lower()


class _TrackedStream(httpx.SyncByteStream):
    """A hand-rolled httpx byte stream that yields multiple pre-set chunks one at a
    time and records how many were actually pulled by the consumer.

    `httpx.MockTransport` normally hands the whole `content=` body to `iter_bytes()`
    as a SINGLE chunk (see the docstring on
    `test_acquire_httpx_streams_abort_when_content_length_lies_or_is_absent` above),
    which can't distinguish a true mid-stream abort from a buffer-everything-then-check
    implementation. Passing a `stream=` (an `httpx.SyncByteStream`) to `httpx.Response`
    instead makes `iter_bytes()` pull genuinely one chunk at a time from this class,
    so `pulled_count` after the loop tells us exactly how many chunks the accumulation
    loop consumed before stopping -- the fidelity signal the naive/real implementations
    disagree on.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.pulled_count = 0

    def __iter__(self):
        for chunk in self._chunks:
            self.pulled_count += 1
            yield chunk

    def close(self) -> None:
        """No real resource to release -- chunks are an in-memory list."""


def test_acquire_httpx_aborts_mid_stream_before_consuming_all_chunks() -> None:
    """Higher-fidelity companion to
    `test_acquire_httpx_streams_abort_when_content_length_lies_or_is_absent`: proves
    the accumulation loop stops READING chunks the moment the running total exceeds
    max_bytes, instead of first draining the whole multi-chunk body into memory and
    checking length afterward.

    Three 60-byte chunks, max_bytes=100: after chunk 1 (total=60, under cap) and
    chunk 2 (total=120, over cap) the loop must abort -- chunk 3 must NEVER be pulled
    from the underlying stream. This is exactly the OOM defense the streaming switch
    exists for: a naive "list(iter_bytes()) then check len" implementation would
    pull all 3 chunks before checking, and this assertion would catch that regression.
    """
    stream = _TrackedStream([b"a" * 60, b"b" * 60, b"c" * 60])

    def handler(_request: httpx.Request) -> httpx.Response:
        # No content-length header -- forces the mid-stream guard (not the pre-check)
        # to be the one that catches the oversized body, same as the sibling test.
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=stream)

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/multi-chunk", client=client, max_bytes=100)

    assert result.ok is False
    assert result.tier == "T0"
    assert result.error is not None
    assert "cap" in result.error.lower()
    # The proof: the loop aborted after the 2nd chunk pushed total (120) over max_bytes
    # (100) -- the 3rd chunk was never requested from the stream. A buffer-then-check
    # implementation would have pulled all 3 chunks before ever comparing to max_bytes.
    assert stream.pulled_count == 2


def test_acquire_httpx_under_cap_succeeds_with_unchanged_result_shape() -> None:
    """A normal small body (under max_bytes) succeeds -- proves the streaming switch
    didn't change the success-path AcquireResult (payload, encoding, content_type,
    status, final_url all match the pre-streaming `.get()` behaviour)."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>hi</p>"
        )

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/small", client=client, max_bytes=100)

    assert result.ok is True
    assert result.payload == b"<p>hi</p>"
    assert result.kind == "bytes"
    assert result.tier == "T0"
    assert result.http_status == 200
    assert result.final_url == "https://example.test/small"
    assert "html" in result.content_type
    assert result.encoding is not None
    assert result.error is None


def test_acquire_httpx_default_max_bytes_is_the_module_constant() -> None:
    """Calling _acquire_httpx without max_bytes uses the real ~25MB default -- a
    normal small body is nowhere near it and succeeds without needing the param."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/small", client=client)

    assert result.ok is True
    assert result.payload == b"<p>hi</p>"


def test_acquire_via_conductor_seam_still_succeeds_under_the_cap() -> None:
    """acquire() (the T0 entrypoint used by the real ladder) still returns a clean
    success for a small body -- the cap plumbing doesn't leak into the public seam."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client)

    assert result.ok is True
    assert result.payload == b"<p>hi</p>"
    assert result.tier == "T0"


def test_acquire_httpx_byte_sniff_routing_unaffected_by_cap_guard() -> None:
    """Regression: a mislabeled PDF (application/octet-stream
    whose bytes start %PDF-) still comes back with the exact bytes needed for
    sniff_kind to correct it to "pdf" -- the cap only bounds size, it never
    alters payload/content_type used for routing."""
    from spyglass_service.content_routing import sniff_kind

    pdf_body = b"%PDF-1.4 mislabeled pdf body"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/octet-stream"}, content=pdf_body
        )

    with client_for(handler) as client:
        result = _acquire_httpx("https://example.test/download", client=client, max_bytes=1000)

    assert result.ok is True
    assert result.payload == pdf_body
    assert sniff_kind(result.content_type, result.payload[:64]) == "pdf"


def test_acquire_curl_cffi_content_length_precheck_aborts(monkeypatch) -> None:
    """T1 (curl_cffi) best-effort cap: a declared Content-Length over the cap aborts
    with the same legible failure shape, before the (already-buffered) content is
    inspected further."""
    import sys
    import types

    from spyglass_service import fetch_acquire

    fake_response = types.SimpleNamespace(
        status_code=200,
        headers={"content-type": "application/octet-stream", "content-length": "999999999"},
        content=b"z" * 10,
        url="https://example.test/huge-curl",
        encoding="utf-8",
    )
    fake_module = types.SimpleNamespace(get=lambda *_a, **_k: fake_response)
    fake_curl_cffi = types.ModuleType("curl_cffi")
    fake_curl_cffi.requests = fake_module
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl_cffi)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_module)

    result = fetch_acquire._acquire_curl_cffi("https://example.test/huge-curl", max_bytes=100)

    assert result.ok is False
    assert result.tier == "T1"
    assert result.error is not None
    assert "cap" in result.error.lower()


def test_acquire_curl_cffi_post_fetch_length_guard_aborts(monkeypatch) -> None:
    """T1 best-effort cap, no-Content-Length case: curl_cffi already buffered the
    whole body (that's its nature -- no true streaming available), so the guard is
    a post-fetch len(content) check against max_bytes."""
    import sys
    import types

    from spyglass_service import fetch_acquire

    fake_response = types.SimpleNamespace(
        status_code=200,
        headers={"content-type": "application/octet-stream"},  # no content-length
        content=b"z" * 500,
        url="https://example.test/lying-curl",
        encoding="utf-8",
    )
    fake_module = types.SimpleNamespace(get=lambda *_a, **_k: fake_response)
    fake_curl_cffi = types.ModuleType("curl_cffi")
    fake_curl_cffi.requests = fake_module
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl_cffi)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_module)

    result = fetch_acquire._acquire_curl_cffi("https://example.test/lying-curl", max_bytes=100)

    assert result.ok is False
    assert result.tier == "T1"
    assert result.error is not None
    assert "cap" in result.error.lower()


def test_acquire_curl_cffi_under_cap_succeeds_unchanged(monkeypatch) -> None:
    """T1 success path is unchanged by the cap guard when under the limit."""
    import sys
    import types

    from spyglass_service import fetch_acquire

    fake_response = types.SimpleNamespace(
        status_code=200,
        headers={"content-type": "text/html"},
        content=b"<p>via curl_cffi</p>",
        url="https://example.test/a",
        encoding="utf-8",
    )
    fake_module = types.SimpleNamespace(get=lambda *_a, **_k: fake_response)
    fake_curl_cffi = types.ModuleType("curl_cffi")
    fake_curl_cffi.requests = fake_module
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl_cffi)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_module)

    result = fetch_acquire._acquire_curl_cffi("https://example.test/a", max_bytes=100)

    assert result.ok is True
    assert result.payload == b"<p>via curl_cffi</p>"
    assert result.tier == "T1"


# ---------------------------------------------------------------------------
# attempts trail: acquire() must not lose earlier
# rungs' failure info on a multi-tier give-up -- each attempt (T0 + every rung
# actually called) is recorded, so the conductor can compose a legible reason
# that names the ORIGINAL block, not just the last rung's error.
# ---------------------------------------------------------------------------


def test_acquire_result_attempts_defaults_to_empty_tuple() -> None:
    """Existing AcquireResult constructions (no `attempts` kwarg) are unaffected."""
    result = AcquireResult(
        payload=b"ok", kind="bytes", final_url="https://example.test/a",
        content_type="text/html", tier="T0", http_status=200, error=None, ok=True,
    )
    assert result.attempts == ()


def test_acquire_success_at_t0_has_single_attempt_entry() -> None:
    """A clean T0 200 records exactly one attempt: (T0, 200, None)."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[])

    assert result.attempts == (("T0", 200, None),)


def test_acquire_escalation_trail_records_every_attempt_in_order() -> None:
    """T0 blocked (403) then a rung also fails: attempts has BOTH entries, in order.

    `acquire()` must not return only the last rung's AcquireResult, silently dropping
    the ORIGINAL T0 block signal. The trail carries every attempt made, so the
    conductor can compose "blocked at T0 (HTTP 403); T1 also failed: ..." instead of a
    bare last-rung error.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    def fake_rung(url: str) -> AcquireResult:
        return _failed_curl_result(url)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[fake_rung])

    assert result.ok is False
    assert result.attempts == (
        ("T0", 403, "HTTP 403"),
        ("T1", 403, "HTTP 403"),
    )


def test_acquire_escalation_trail_across_t0_t1_t2_t3_all_fail() -> None:
    """A four-rung give-up records all four attempts, each tier represented once."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    def make_failed(tier: str, status: int, error: str):
        def rung(url: str) -> AcquireResult:
            return AcquireResult(
                payload=b"", kind="bytes", final_url=url, content_type="",
                tier=tier, http_status=status, error=error, ok=False,
            )
        rung.tier = tier
        return rung

    rungs = [
        make_failed("T1", 403, "HTTP 403"),
        make_failed("T2", None, "jina timeout"),
        make_failed("T3", None, "browser transport error"),
    ]

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=rungs)

    assert result.ok is False
    tiers_seen = [entry[0] for entry in result.attempts]
    assert tiers_seen == ["T0", "T1", "T2", "T3"]
    assert result.attempts[0] == ("T0", 503, "HTTP 503")
    assert result.attempts[2] == ("T2", None, "jina timeout")


def test_acquire_trail_stops_accumulating_once_a_rung_succeeds() -> None:
    """Escalation stops at the first ok+unblocked rung; the trail reflects only the
    attempts actually made (T0 block + the winning rung), not the full ladder."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    def winning_rung(url: str) -> AcquireResult:
        return _ok_curl_result(url)

    def never_called(_url: str) -> AcquireResult:
        raise AssertionError("must not be called after a rung succeeds")

    with client_for(handler) as client:
        result = acquire(
            "https://example.test/a", client=client, rungs=[winning_rung, never_called]
        )

    assert result.ok is True
    assert result.attempts == (
        ("T0", 403, "HTTP 403"),
        ("T1", 200, None),
    )


def test_acquire_empty_rungs_t0_only_block_has_one_attempt() -> None:
    """rungs=[] (T0-only) records just the T0 attempt, matching the no-escalation path."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with client_for(handler) as client:
        result = acquire("https://example.test/a", client=client, rungs=[])

    assert result.attempts == (("T0", 429, "HTTP 429"),)
