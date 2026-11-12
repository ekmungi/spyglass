"""The one way the reader builders fetch a web page: a `Page` value and a fetcher callable.

Builders never touch the network directly. They receive a `Fetcher` (`fetch(url, headers=None)`)
so tests can inject canned pages. The default fetcher sends plain requests through the engine's
acquire ladder (plain GET, then curl_cffi, Jina and the browser rung as configured) and keeps the
per-domain "which rung wins" cache current. A request with custom headers (the GitHub API) is a
single direct GET, because the ladder cannot carry per-request headers. Before either, the
redirect chain is walked by hand (`redirects.resolve_redirects`); a failed or over-long walk
refuses the fetch. That walk is only an early exit: the guarantee is structural. The client
re-checks every request and redirect hop (`netguard.guard_client`), the curl_cffi rung follows
redirects by hand with the same check, and once any request has been refused no later rung runs.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from sqlalchemy import Engine

from spyglass_service.radar import netguard
from spyglass_service.content_routing import classify_url, sniff_kind
from spyglass_service.documents import build_client as _plain_client
from spyglass_service.fetch_acquire import AcquireResult, acquire
from spyglass_service.fetch_cache import domain_of, get_cached_tier, record_winning_tier
from spyglass_service.fetch_failure import compose_failure_fields
from spyglass_service.fetch_rungs import build_rungs
from spyglass_service.radar.reader.redirects import resolve_redirects

logger = logging.getLogger(__name__)


class BuildFailure(Exception):
    """A builder could not produce a document; the message is stored as the reader-facing reason.

    `transient` marks a passing failure (see `Page.transient`): it should be retried soon rather
    than stored with the long retry delay.
    """

    def __init__(self, message: str = "", *, transient: bool = False) -> None:
        """Keep the reason and whether the failure is passing."""
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class Page:
    """A fetched document: either usable content or a short, human-readable failure reason."""

    url: str
    ok: bool
    body: bytes | str = b""
    content_type: str = ""
    status: int | None = None
    encoding: str | None = None
    error: str | None = None
    # True when a rung already turned the page into markdown (the Jina Reader rung).
    is_markdown: bool = False
    # True when the failure is passing (the name could not be looked up, the network failed or
    # timed out): it should be retried soon rather than remembered as a lasting failure.
    transient: bool = False

    @property
    def text(self) -> str:
        """The body decoded to text (with the response's charset, falling back to UTF-8)."""
        if isinstance(self.body, str):
            return self.body
        return self.body.decode(self.encoding or "utf-8", errors="replace")

    @property
    def is_pdf(self) -> bool:
        """True when the content type or the leading bytes say this is a PDF."""
        if isinstance(self.body, str):
            return False
        return sniff_kind(self.content_type, self.body[:256]) == "pdf"


Fetcher = Callable[..., Page]


_REFUSED = "This address cannot be fetched."
# The reason given when a host name could not be looked up or the network failed for a moment.
UNREACHABLE = netguard.UNREACHABLE


def failed_page(url: str, error: str, status: int | None = None, *,
                transient: bool = False) -> Page:
    """A `Page` that records a failure; `transient` marks a passing one (see `Page.transient`)."""
    return Page(url=url, ok=False, status=status, error=error, transient=transient)


def _refusal(url: str, reach: netguard.Reach) -> Page | None:
    """The failed page for an address that may not be fetched now, or None when it may."""
    if reach is netguard.Reach.UNRESOLVED:
        return failed_page(url, UNREACHABLE, transient=True)
    if reach is not netguard.Reach.PUBLIC:
        return failed_page(url, _REFUSED)
    return None


def build_client() -> httpx.Client:
    """The document client with the public-address check on every request and redirect hop."""
    return netguard.guard_client(_plain_client())


def _halt_after_block(rung: Callable, client: httpx.Client) -> Callable:
    """Wrap a ladder rung so it does nothing once the guarded client has refused an address.

    Without this a refused redirect would count as an ordinary transport failure and the ladder
    would go on to try the same address with its other methods.
    """

    def guarded_rung(url: str):
        """Run the rung unless an address was refused during this fetch."""
        if netguard.was_blocked(client):
            return AcquireResult(payload=b"", kind="bytes", final_url=url, content_type="",
                                 tier=getattr(rung, "tier", "T1"), http_status=None,
                                 error=_REFUSED, ok=False)
        return rung(url)

    guarded_rung.tier = getattr(rung, "tier", "T1")  # type: ignore[attr-defined]
    return guarded_rung


def _from_acquire(result: AcquireResult) -> Page:
    """Convert the ladder's result into a `Page`, composing the failure reason on error."""
    if not result.ok:
        failure = compose_failure_fields(result.attempts, detected_type=result.content_type or None)
        return failed_page(result.final_url, str(failure.get("error") or result.error or "fetch failed"),
                           result.http_status)
    return Page(
        url=result.final_url,
        ok=True,
        body=result.payload,
        content_type=result.content_type,
        status=result.http_status,
        encoding=result.encoding,
        is_markdown=result.kind == "markdown",
    )


def make_fetcher(settings, engine: Engine | None = None) -> Fetcher:
    """Build the default fetcher for `settings` (and `engine` for the per-domain tier cache)."""

    def fetch(url: str, headers: Mapping[str, str] | None = None) -> Page:
        """GET `url`; with `headers`, a single direct request, otherwise the full ladder."""
        refused = _refusal(url, netguard.check_url(url))
        if refused is not None:
            return refused
        client = build_client()
        try:
            # Walk the redirect chain by hand first: the ladder's client would follow it blindly.
            walked = resolve_redirects(client, url)
            if walked.blocked:
                return failed_page(url, UNREACHABLE if walked.transient else _REFUSED,
                                   transient=walked.transient)
            url = walked.url
            if headers:
                try:
                    resp = client.get(url, headers=dict(headers))
                except httpx.HTTPError as exc:
                    if netguard.was_blocked(client):
                        return failed_page(url, _REFUSED)
                    if isinstance(exc, (httpx.TransportError, netguard.UnresolvedAddress)):
                        return failed_page(url, UNREACHABLE, transient=True)
                    return failed_page(url, f"request failed: {exc.__class__.__name__}")
                refused = _refusal(url, netguard.check_url(str(resp.url)))
                if refused is not None:
                    return refused
                if resp.status_code != 200:
                    return failed_page(str(resp.url), f"HTTP {resp.status_code}", resp.status_code)
                return Page(url=str(resp.url), ok=True, body=resp.content,
                            content_type=resp.headers.get("content-type", ""),
                            status=resp.status_code, encoding=resp.encoding)
            kind = classify_url(url) or "html"
            domain = domain_of(url) if engine is not None else None
            cached = get_cached_tier(engine, domain) if engine is not None else None
            if cached == "T2":
                # A domain pinned to the Jina rung (which returns flattened markdown) is retried from
                # the start: the reader wants real HTML with its images and tables whenever it can get it.
                cached = None
            rungs = tuple(_halt_after_block(r, client)
                          for r in build_rungs(settings, kind, guarded=True))
            result = acquire(url, client=client, target_kind=kind, rungs=rungs, start_tier=cached)
            if netguard.was_blocked(client):
                return failed_page(url, _REFUSED)
            if engine is not None and result.ok and result.tier != "T0":
                record_winning_tier(engine, domain, result.tier)
            if result.final_url:
                # A page that redirected to this computer or a private network is never read.
                refused = _refusal(url, netguard.check_url(result.final_url))
                if refused is not None:
                    return refused
            return _from_acquire(result)
        finally:
            client.close()

    return fetch
