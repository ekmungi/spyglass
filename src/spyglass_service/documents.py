"""Download the document behind a bookmark link and extract its text.

Used by the curation skill to read the actual paper/article (not just the link)
before summarizing it into a vault briefing. `fetch_fulltext` is the thin conductor:
it routes a URL to the right lane (YouTube transcript / GitHub README / generic
acquire+extract), delegating the actual network fetch to `fetch_acquire.acquire`
and content-to-text conversion to `extractors.*`.
"""

import re
from collections.abc import Callable, Sequence

import httpx

from .content_routing import classify_url, sniff_kind
from .feed_http import BROWSER_USER_AGENT
from .extractors.html import extract_markdown
from .extractors.pdf import extract_pdf
from .extractors.transcript import (
    _default_cli_runner,
    _fetch_transcript_via_cli,
    _fetch_transcript_youtube_api,
    _yt_transcribe_cmd,
    set_yt_transcribe_cmd,
)
from .extractors import transcript as _transcript_module
from .fetch_acquire import AcquireResult, acquire
from .fetch_cache import domain_of, get_cached_tier, record_winning_tier
from .fetch_failure import compose_failure_fields, finish
from .fetch_rungs import build_rungs
from .radar import netguard

# arXiv abstract pages have a matching PDF; prefer the PDF for real content.
_ARXIV_ABS = re.compile(r"^(https?://arxiv\.org)/abs/(.+)$")
# YouTube videos: full text means the caption transcript, not the page HTML.
_YT_VIDEO = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)([\w-]{6,})"
)
# GitHub repo root URL (NOT a /blob/, /tree/, /releases/, etc. sub-path, and NOT /orgs/,
# /settings/, /explore/, /notifications/, /marketplace/ etc. non-repo pages). The README
# is the ideal readable input; fetch it raw (no API token).
_GITHUB_REPO = re.compile(
    r"^https?://(?:www\.)?github\.com/"
    r"(?!(?:orgs|settings|explore|notifications|marketplace)/)"
    r"([^/]+)/([^/]+?)(?:\.git)?/?(?:[?#]|$)"
)
# Browser-like UA: many article/paper hosts 403 the default python-httpx agent. Shared with the
# feed fetching (feed_http.py) so every request Spyglass makes looks the same.
_USER_AGENT = BROWSER_USER_AGENT

__all__ = [
    "build_client",
    "normalize_url",
    "extract_markdown",
    "fetch_page_title",
    "set_yt_transcribe_cmd",
    "fetch_fulltext",
    "fetch_document",
    # Re-exported for backward-compat importers/tests (this state now lives in
    # extractors/transcript.py).
    "_default_cli_runner",
    "_yt_transcribe_cmd",
    "_fetch_transcript_via_cli",
    "_fetch_transcript_youtube_api",
]


def __getattr__(name: str) -> object:
    """Proxy `_YT_CMD` to its single source of truth in extractors.transcript.

    A plain re-export (``from .extractors.transcript import _YT_CMD``) would copy the
    value at import time and go stale the moment ``set_yt_transcribe_cmd`` rebinds it
    there. PEP 562 module __getattr__ instead reads the live value on each access, so
    `documents._YT_CMD` always reflects the current command without duplicating state.
    """
    if name == "_YT_CMD":
        return _transcript_module._YT_CMD
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_client() -> httpx.Client:
    """An httpx client tuned for document fetching: browser UA + follow redirects, guarded.

    Guarded means public addresses only on every redirect hop, reads only, no cookies (netguard).
    """
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    return netguard.guard_client(client)


def normalize_url(url: str) -> str:
    """Rewrite known landing pages to their document URL (arXiv abs -> pdf)."""
    match = _ARXIV_ABS.match(url)
    if match:
        return f"{match.group(1)}/pdf/{match.group(2)}"
    return url


def _fetch_github_readme(owner: str, repo: str, client: httpx.Client) -> str | None:
    """Fetch a repo's README as raw markdown from githubusercontent (no API/token needed).

    Tries HEAD/main/master branches x .md/.rst/.txt extensions. Returns the first non-empty
    200 body, or None if no README is found (caller falls through to the generic extractor).
    """
    for branch in ("HEAD", "main", "master"):
        for ext in (".md", ".rst", ".txt"):
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README{ext}"
            try:
                resp = client.get(url)
            except httpx.HTTPError:
                continue  # try the next candidate; a transient error is not fatal here
            if resp.status_code == 200 and resp.text.strip():
                return resp.text
    return None


# --- YouTube transcripts: re-export the transcript lane's private helpers so ------------
# existing importers/tests keep working unchanged (documents.py used to own this state).
# `_fetch_transcript` below is a thin wrapper (not a straight re-export) so that monkeypatching
# `documents._fetch_transcript_via_cli` / `documents._fetch_transcript_youtube_api` (as the
# existing test suite does) still takes effect -- it resolves those names from documents' own
# module namespace at call time, mirroring the pre-refactor behaviour.


def _fetch_transcript(video_id: str) -> str | None:
    """A video's transcript text: the robust yt-transcribe CLI first, caption-API fallback.

    Thin wrapper over extractors.transcript -- resolves `_fetch_transcript_via_cli` /
    `_fetch_transcript_youtube_api` from THIS module's namespace (not a fixed closure over
    extractors.transcript) so tests that monkeypatch documents._fetch_transcript_via_cli /
    documents._fetch_transcript_youtube_api still change this function's behaviour.
    """
    text = _fetch_transcript_via_cli(f"https://www.youtube.com/watch?v={video_id}")
    if text is not None:
        return text
    try:
        return _fetch_transcript_youtube_api(video_id)
    except Exception:  # noqa: BLE001 -- the fallback lib raises rich custom errors; treat as no-text
        return None


def _fetch_transcript_by_url(url: str) -> str | None:
    """A video's transcript text given its ORIGINAL url (vimeo support).

    `_fetch_transcript` reconstructs a youtube watch URL from a captured video id --
    that reconstruction is wrong for a non-youtube host (e.g. vimeo). yt-dlp (which
    the yt-transcribe CLI shells out to) resolves any supported host's URL directly,
    so this hands the CLI the URL as-is instead of rebuilding it. There is no
    caption-API fallback here (youtube-transcript-api is youtube-only) -- CLI failure
    means no transcript for a non-youtube host.
    """
    return _fetch_transcript_via_cli(url)


def fetch_fulltext(
    url: str,
    client: httpx.Client | None = None,
    html_extractor: Callable[[str], str] | None = None,
    pdf_extractor: Callable[[bytes], str] | None = None,
    transcript_fetcher: Callable[[str], str | None] | None = None,
    acquire_rungs: Sequence[Callable[[str], AcquireResult]] | None = None,
    *,
    settings=None,
    engine=None,
) -> dict:
    """Fetch a document and return its full text as clean markdown for the DB store.

    Returns {markdown, content_type, status, error, source_url, detected_type,
    tier_reached, http_status, error_class} -- the last 4 are the structured,
    card-visible failure record (see fetch_failure.py for
    the error_class mapping and legible-reason composition from the acquire()
    attempts trail). PDFs are extracted from bytes (no file written); other pages are
    readable-extracted to markdown. A non-success response is status "failed"; empty
    extraction "empty". Unlike fetch_document, this never writes to the vault -- the
    markdown is stored in SQLite by content_store.

    Routes classify_url (transcript: youtube/vimeo) -> (github readme) -> normalize ->
    acquire (the fetch layer) -> sniff_kind -> pdf/image/html extractor.

    Rung precedence, highest first:
      1. `acquire_rungs` explicit (including `[]`) -- always wins; this is what tests
         use to pin a deterministic/offline ladder.
      2. `build_rungs(settings, ladder_kind)` when `settings` is given (and
         `acquire_rungs` is not) -- the real Settings-driven ladder (curl_cffi
         always, + Jina iff `settings.jina_enabled`, + the browser rung iff
         `settings.browser_enabled` AND `ladder_kind == "html"`).
      3. Neither given -> `rungs=None` passed to `acquire()`, i.e. its own
         `_DEFAULT_RUNGS` (curl-only) fallback.
    enrich.enrich_item passes `settings` and `engine`. The MCP store_fulltext tool (via
    fulltext.fetch_card_fulltext) passes neither, so it gets the curl-only fallback and no
    per-domain cache.

    Per-domain method cache: when `engine` is given, the
    target domain's last-known winning tier (fetch_cache.get_cached_tier) is looked up
    and passed to `acquire()` as `start_tier`, skipping every lower-tier attempt that
    domain is already known to fail -- an automatic batch pays the escalation cost once
    per DOMAIN, not once per URL. After a SUCCESSFUL acquire, the winning tier is
    recorded back IFF it is above T0 (`result.tier != "T0"`) -- a T0-friendly domain is
    never pinned, so it keeps starting cheap every time; only a domain that genuinely
    needed escalation gets pinned to its winning tier. A failed acquire records
    nothing. `engine=None` (the default) skips the cache
    entirely -- no lookup, no record, behaviour-preserving.

    Accepted limitation: a domain pinned above T0 never re-probes the lower tiers it
    skipped, even if whatever blocked it there later lifts -- this cache only ever
    escalates further up on a regression, it never re-tries down. A future task could
    add a periodic re-probe (e.g. occasionally trying T0 again for a pinned domain);
    out of scope here.
    """
    video = _YT_VIDEO.search(url)
    if video:
        # The watch page is a consent-walled app shell; the transcript IS the text. Default path
        # reuses the yt-transcribe CLI (robust), falling back to the caption API.
        try:
            transcript = (transcript_fetcher or _fetch_transcript)(video.group(1))
        except Exception as error:  # the transcript lib raises rich custom errors
            return finish({"markdown": "", "content_type": "youtube/transcript",
                            "status": "failed", "error": str(error)[:300], "source_url": url})
        return finish({
            "markdown": transcript or "", "content_type": "youtube/transcript",
            "status": "ok" if transcript else "empty", "error": None, "source_url": url,
        })

    if classify_url(url) == "transcript":
        # Non-youtube transcript host (vimeo). Unlike youtube, there is no
        # video-id capture group to reconstruct a canonical URL from -- yt-dlp (which
        # the CLI shells out to) resolves the ORIGINAL url directly, so hand it that
        # instead of rebuilding a (wrong, youtube-shaped) watch URL. No caption-API
        # fallback: youtube-transcript-api is youtube-only.
        try:
            transcript = (transcript_fetcher or _fetch_transcript_by_url)(url)
        except Exception as error:  # the transcript lib raises rich custom errors
            return finish({"markdown": "", "content_type": "youtube/transcript",
                            "status": "failed", "error": str(error)[:300], "source_url": url})
        return finish({
            "markdown": transcript or "", "content_type": "youtube/transcript",
            "status": "ok" if transcript else "empty", "error": None, "source_url": url,
        })

    # GitHub repo pages are interactive app shells -- trafilatura finds no prose. The README is
    # the ideal input (already markdown); fetch it raw (no token). A /blob/ or /tree/ URL does
    # not match _GITHUB_REPO and falls through to the generic path below.
    target_url = normalize_url(url)
    owns_client = client is None
    client = client or build_client()
    try:
        gh = _GITHUB_REPO.match(url)
        if gh:
            readme = _fetch_github_readme(gh.group(1), gh.group(2), client)
            if readme:
                return finish({"markdown": readme, "content_type": "text/markdown",
                                "status": "ok", "error": None, "source_url": url})
            # No README found -> fall through to the generic path
            # (may still extract something). The same client is reused.

        # Pre-fetch ladder kind: classify_url already routed
        # transcript URLs away above, so only "pdf"/"image"/None remain here. Default
        # a None (nothing recognizable in the URL) to "html" -- this is what gates the
        # browser rung (T3) INTO the ladder for ordinary pages and OUT of it for a
        # recognized pdf/image URL, since build_rungs only ever adds the browser rung
        # when target_kind == "html".
        ladder_kind = classify_url(target_url) or "html"

        # Rung precedence (see the fetch_fulltext docstring above): an explicit acquire_rungs always
        # wins (incl. []); else a given settings builds the real Settings-driven ladder;
        # else None so acquire() falls back to its own curl-only _DEFAULT_RUNGS.
        if acquire_rungs is not None:
            effective_rungs = acquire_rungs
        elif settings is not None:
            effective_rungs = build_rungs(settings, ladder_kind)
        else:
            effective_rungs = None

        # Per-domain method cache: only consulted when an engine is given
        # (see the fetch_fulltext docstring's "Accepted limitation" section above).
        domain = domain_of(target_url) if engine is not None else None
        cached_tier = get_cached_tier(engine, domain) if engine is not None else None

        result = acquire(
            target_url, client=client, target_kind=ladder_kind, rungs=effective_rungs,
            start_tier=cached_tier,
        )

        if engine is not None and result.ok and result.tier != "T0":
            # Record only an ABOVE-T0 win -- see the docstring's record-only-if-above-T0
            # rule. A T0 win is deliberately never written so an easy domain keeps
            # starting the ladder at T0 (cheapest) on every subsequent fetch.
            record_winning_tier(engine, domain, result.tier)
    finally:
        if owns_client:
            client.close()

    if not result.ok:
        # Structured, card-visible failure: the FULL attempts trail (not
        # just this last-attempted result) composes `error`, naming the original
        # block AND every later tier's failure.
        failure = compose_failure_fields(result.attempts, detected_type=result.content_type or None)
        return finish(
            {"markdown": "", "content_type": "", "status": "failed",
             "error": failure["error"], "source_url": result.final_url},
            **failure,
        )

    # Winning tier: populated on success too (not failure-only) -- see fetch_failure.py.
    _won = {"tier_reached": result.tier}

    if result.kind == "markdown":
        # A rung (Jina Reader, T2) already rendered + extracted the page server-side --
        # use its payload directly. No sniff_kind, no HTML/PDF extractor: running either
        # over already-clean markdown would be redundant at best and corrupt at worst
        # (e.g. trafilatura re-parsing markdown as if it were raw HTML). Also how a
        # Jina-won PDF is handled -- Jina already extracted its text.
        markdown = result.payload
        return finish({
            "markdown": markdown,
            "content_type": result.content_type,
            "status": "ok" if markdown else "empty",
            "error": None,
            "source_url": result.final_url,
        }, detected_type=result.content_type or "markdown", **_won)

    if result.kind == "html":
        # The browser rung (T3, patchright) already rendered the page (JS executed)
        # and handed back a decoded str of HTML -- unlike a "bytes" payload, this
        # needs NO charset decode and NO sniff_kind (there is nothing to sniff: the
        # rung only ever produces HTML, never a PDF/image). It still needs the HTML
        # extractor though (unlike Jina's "markdown" kind, which is already
        # pre-extracted) -- trafilatura strips nav/boilerplate from the rendered markup.
        markdown = extract_markdown(result.payload, html_extractor).strip()
        return finish({
            "markdown": markdown,
            "content_type": result.content_type,
            "status": "ok" if markdown else "empty",
            "error": None,
            "source_url": result.final_url,
        }, detected_type="html", **_won)

    content_type = result.content_type
    # Prefer a decisive pre-fetch kind (e.g. a .pdf/.png URL extension) but let the
    # byte-sniff CORRECT it when the header/bytes disagree with that guess (a .pdf
    # URL that actually serves an HTML error page, or vice versa) -- sniff_kind
    # already treats the byte-sniff as ground truth over an ambiguous header, so
    # always computing it here (rather than short-circuiting on the pre-fetch kind)
    # keeps a single source of truth for the final decision. Gated on kind == "bytes"
    # (the only kind that reaches this line, since "markdown" returned above) so the
    # payload[:256] slice is never attempted against a str payload from a future
    # non-bytes, non-markdown rung kind.
    kind = sniff_kind(content_type, result.payload[:256])

    if kind == "pdf":
        markdown = extract_pdf(result.payload, pdf_extractor).strip()
        return finish({
            "markdown": markdown,
            "content_type": content_type,
            "status": "ok" if markdown else "empty",
            "error": None,
            "source_url": result.final_url,
        }, detected_type="pdf", **_won)

    if kind == "image":
        # No image extractor yet (vision-LLM OCR is not built) -- an honest empty/deferred
        # stub rather than silently running the HTML extractor over binary image bytes
        # (which today already yields "" via trafilatura, but for the wrong reason).
        return finish({
            "markdown": "",
            "content_type": content_type,
            "status": "empty",
            "error": "image extraction deferred (vision extraction not built yet)",
            "source_url": result.final_url,
        }, detected_type="image", error_class="empty_extraction", **_won)

    # Decode with the charset acquire() resolved (from the response's declared
    # Content-Type, mirroring httpx's own `.text` behaviour) -- not a hardcoded
    # "utf-8" -- so a non-UTF-8 page (e.g. charset=iso-8859-1) decodes correctly
    # instead of every non-ASCII byte becoming U+FFFD.
    markdown = extract_markdown(
        result.payload.decode(result.encoding or "utf-8", errors="replace"), html_extractor
    ).strip()

    return finish({
        "markdown": markdown,
        "content_type": content_type,
        "status": "ok" if markdown else "empty",
        "error": None,
        "source_url": result.final_url,
    }, detected_type="html", **_won)


# --- Disk-download + title-repair: re-exported from documents_download.py so ------
# existing importers/monkeypatches (documents.fetch_document, documents.fetch_page_title) keep
# resolving unchanged. Placed at the BOTTOM of the module (after build_client/normalize_url are
# defined) because documents_download imports those two names back from documents lazily inside
# its functions -- a top-of-file import here would still work either way, but bottom-of-file
# keeps the one-directional dependency visually obvious: documents_download depends on documents,
# never the reverse, avoiding an import cycle.
from .documents_download import fetch_document, fetch_page_title  # noqa: E402
