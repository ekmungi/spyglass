"""HTML -> readable markdown extraction (trafilatura), injectable for tests.

Moved out of documents.py so the extractor is a testable unit on its
own, independent of the acquire/routing logic in the conductor. It also has a
readability-lxml fallback: some page layouts defeat
trafilatura's heuristics (e.g. unconventional markup, heavy client-rendered
scaffolding) but readability's older Arc90 "readability" algorithm still finds
the main content block on the same HTML.
"""

from collections.abc import Callable

# Below this many characters, the primary extractor's output is treated as too thin
# to trust and the fallback is tried on the same HTML. ~200 chars is roughly one
# short paragraph -- enough to rule out "extractor found basically nothing" (an empty
# div, a single nav label) while not being so high that genuinely short articles
# (e.g. a terse blog post) needlessly trigger a second extraction pass.
_MIN_PRIMARY_CHARS = 200


def _extract_markdown_default(html: str) -> str:
    """Default readable extractor: trafilatura to markdown (imported lazily)."""
    import trafilatura

    return trafilatura.extract(html, output_format="markdown", include_links=True) or ""


def _readability_fallback(html: str) -> str:
    """Fallback readable extractor: readability-lxml's Arc90 algorithm (imported
    lazily, matching the trafilatura import pattern -- keeps it off the module-load
    path and out of the `filterwarnings=["error"]` test run).

    readability.Document(html).summary() returns cleaned main-content HTML (boilerplate
    like nav/footer stripped, but content tags like <p>/<article> still present) --
    strip those tags down to plain text with BeautifulSoup (already a project
    dependency) for a lightweight, dependency-light "good enough" text, not perfect
    markdown. Never raises: unparseable input normalizes to "" so the conductor can
    record an empty result instead of crashing.
    """
    from bs4 import BeautifulSoup
    from readability import Document

    try:
        summary_html = Document(html).summary()
    except Exception:
        return ""

    text = BeautifulSoup(summary_html, "html.parser").get_text(separator="\n").strip()
    return text


def extract_markdown(
    html: str,
    extractor: Callable[[str], str] | None = None,
    fallback: Callable[[str], str] | None = None,
) -> str:
    """Readable-article markdown from an HTML page.

    Uses a heuristic extractor (trafilatura by default) to drop nav/boilerplate and
    keep the main content as markdown. Both `extractor` (primary) and `fallback` are
    injectable so tests need neither the network nor the real libraries.

    The fallback (readability-lxml by default) only DEFAULT-fires -- on the DEFAULT
    primary path, when its stripped output is shorter than `_MIN_PRIMARY_CHARS`. An
    explicitly injected `extractor` is used as-is: the caller owns extraction, so a
    short result from it is intentional, not a failure, and readability does not
    second-guess it -- UNLESS a `fallback` is also injected, which forces the
    fallback to run (an escape hatch for testing the fallback path itself). When the
    fallback does run, whichever of the two yields more usable (longer, stripped)
    text is returned. Returns "" (never None) when both yield nothing.
    """
    extract = extractor or _extract_markdown_default
    primary = (extract(html) or "").strip()

    if len(primary) >= _MIN_PRIMARY_CHARS:
        return primary

    run_fallback = fallback if fallback is not None else (_readability_fallback if extractor is None else None)
    if run_fallback is None:
        return primary

    fallback_text = (run_fallback(html) or "").strip()

    return fallback_text if len(fallback_text) > len(primary) else primary
