"""Tests for the failure-composition module.

fetch_failure.py is pure logic -- no I/O, no AcquireResult/Content dependency beyond
the plain (tier, http_status, error) trail shape -- so these tests drive it directly
with hand-built attempts tuples, the same shape AcquireResult.attempts produces.
"""

from spyglass_service.fetch_failure import classify_error_class, compose_failure_fields


def test_classify_error_class_blocked_for_block_status() -> None:
    """A 403/429/503 anywhere in the trail classifies as "blocked"."""
    assert classify_error_class([("T0", 403, "HTTP 403")]) == "blocked"
    assert classify_error_class([("T0", 429, "HTTP 429")]) == "blocked"
    assert classify_error_class([("T0", 503, "HTTP 503")]) == "blocked"


def test_classify_error_class_blocked_survives_escalation_to_a_generic_failure() -> None:
    """The ORIGINAL block classifies the whole failure even if the last rung's own
    error looks like a plain transport error -- the give-up is still "blocked"."""
    attempts = [("T0", 403, "HTTP 403"), ("T1", None, "Connection reset")]
    assert classify_error_class(attempts) == "blocked"


def test_classify_error_class_http_error_for_non_block_status() -> None:
    """A definitive non-block HTTP failure (404/410/500) classifies as "http_error"."""
    assert classify_error_class([("T0", 404, "HTTP 404")]) == "http_error"
    assert classify_error_class([("T0", 500, "HTTP 500")]) == "http_error"


def test_classify_error_class_size_cap() -> None:
    """The size-cap message (from fetch_acquire._download_cap_error) classifies distinctly."""
    attempts = [("T0", 200, "download exceeds 25MB cap")]
    assert classify_error_class(attempts) == "size_cap"


def test_classify_error_class_timeout() -> None:
    """A timeout-flavoured transport error classifies as "timeout", not the generic bucket."""
    attempts = [("T0", None, "ReadTimeout: timed out waiting for response")]
    assert classify_error_class(attempts) == "timeout"


def test_classify_error_class_transport_error_for_generic_connect_failure() -> None:
    """A non-timeout transport error (no response reached, no block status) is
    "transport_error" -- the catch-all for a connection reset/refused/DNS failure."""
    attempts = [("T0", None, "ConnectError: [Errno 111] Connection refused")]
    assert classify_error_class(attempts) == "transport_error"


def test_classify_error_class_empty_extraction_when_no_transport_signal() -> None:
    """No attempts at all (e.g. an extractor ran but produced nothing) falls back to
    "empty_extraction" -- there was no fetch failure, just nothing usable extracted."""
    assert classify_error_class([]) == "empty_extraction"


def test_compose_failure_fields_names_original_block_and_later_failure() -> None:
    """The composed reason names the ORIGINAL block AND that later tiers also failed --
    not a bare last-rung error."""
    attempts = [
        ("T0", 403, "HTTP 403"),
        ("T1", None, "Connection reset"),
    ]
    fields = compose_failure_fields(attempts, detected_type="html")
    assert fields["error_class"] == "blocked"
    assert fields["tier_reached"] == "T1"
    assert fields["http_status"] == 403  # original block status preferred over the T1 None
    assert fields["detected_type"] == "html"
    assert "403" in fields["error"]
    assert "T1" in fields["error"]
    assert "Connection reset" in fields["error"]


def test_compose_failure_fields_single_tier_failure_is_still_legible() -> None:
    """A single-attempt failure (no escalation happened) still gets a legible reason,
    not just the raw "HTTP 403" (so every failure, not only multi-tier ones, benefits)."""
    attempts = [("T0", 403, "HTTP 403")]
    fields = compose_failure_fields(attempts, detected_type="html")
    assert fields["error_class"] == "blocked"
    assert fields["tier_reached"] == "T0"
    assert fields["http_status"] == 403
    assert "403" in fields["error"]


def test_compose_failure_fields_four_tier_giveup_names_every_tier() -> None:
    """A full T0->T3 give-up composes a reason that mentions every attempted tier."""
    attempts = [
        ("T0", 403, "HTTP 403"),
        ("T1", 403, "HTTP 403"),
        ("T2", None, "jina timeout"),
        ("T3", None, "browser transport error"),
    ]
    fields = compose_failure_fields(attempts, detected_type="html")
    assert fields["tier_reached"] == "T3"
    assert fields["http_status"] == 403
    assert fields["error_class"] == "blocked"
    for tier in ("T0", "T1", "T2", "T3"):
        assert tier in fields["error"]


def test_compose_failure_fields_prefers_original_block_status_over_last_none() -> None:
    """When the ladder started with a block status but the LAST attempt is a transport
    error (http_status=None), http_status still reports the original block -- the more
    informative signal for a retry decision (per the brief: prefer the block over the
    final tier's None)."""
    attempts = [("T0", 429, "HTTP 429"), ("T1", None, "curl_cffi SSLError")]
    fields = compose_failure_fields(attempts, detected_type="html")
    assert fields["http_status"] == 429


def test_compose_failure_fields_falls_back_to_last_status_when_no_block_present() -> None:
    """Without any block-status attempt, http_status is simply the last attempt's status
    (e.g. a genuine 404 -- no block to prefer)."""
    attempts = [("T0", 404, "HTTP 404")]
    fields = compose_failure_fields(attempts, detected_type="html")
    assert fields["http_status"] == 404
    assert fields["error_class"] == "http_error"


def test_compose_failure_fields_later_attempt_with_no_error_or_status() -> None:
    """A later attempt with neither an error message nor an HTTP status (a bare rung
    failure) still composes a legible fragment ("no response"), not a crash/blank."""
    attempts = [("T0", 403, "HTTP 403"), ("T1", None, None)]
    fields = compose_failure_fields(attempts, detected_type="html")
    assert "no response" in fields["error"]


def test_compose_failure_fields_empty_attempts_yields_empty_extraction() -> None:
    """No attempts at all (e.g. acquire succeeded but extraction produced nothing) still
    returns a usable, non-crashing fields dict."""
    fields = compose_failure_fields([], detected_type="pdf")
    assert fields["error_class"] == "empty_extraction"
    assert fields["tier_reached"] is None
    assert fields["http_status"] is None
    assert fields["detected_type"] == "pdf"
    assert fields["error"]  # a legible (non-empty) message even with no trail


def test_block_statuses_stay_in_sync_with_fetch_acquire() -> None:
    """`_BLOCK_STATUSES` is intentionally duplicated (not
    imported) in fetch_failure.py and fetch_acquire.py so each module stays
    dependency-free of the other (see both modules' docstrings). A drift-guard test is
    the cheapest way to catch the two sets silently diverging if the block-status
    policy ever changes in only one place."""
    from spyglass_service.fetch_acquire import _BLOCK_STATUSES as acquire_block_statuses
    from spyglass_service.fetch_failure import _BLOCK_STATUSES as failure_block_statuses

    assert failure_block_statuses == acquire_block_statuses
