"""Content-type routing for the fetch conductor.

Two pure classifier functions the conductor (documents.fetch_fulltext) consults:
`classify_url` runs BEFORE any network call (cheap, URL-only signals -- domain and
extension); `sniff_kind` runs AFTER a fetch, using the HTTP Content-Type header with
a byte-sniff (puremagic) tiebreaker for an ambiguous or mislabeled response (e.g. a
real PDF served as `application/octet-stream`). Neither function performs I/O or
touches the acquire ladder or the extractor choice -- they only decide
which lane a URL/response belongs to.
"""

import re
from typing import Literal

import puremagic

# The kinds of content the conductor can route to. "transcript" is decided pre-fetch
# only (a video is never fetched as a page); "pdf" / "image" / "html" can be decided
# either pre-fetch (from the URL) or post-fetch (from headers/bytes).
TargetKind = Literal["transcript", "pdf", "image", "html"]

# Mirrors documents._YT_VIDEO exactly -- kept as a private copy (not an import) so this
# module has no dependency on documents.py; the two must stay behaviourally identical
# (see the T2 brief's "keep youtube byte-for-byte" requirement).
_YT_VIDEO = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)([\w-]{6,})"
)
# Vimeo: any vimeo.com/<numeric-id> style URL. Unlike youtube, we don't need to
# capture an id -- the transcript lane hands the CLI the original URL for vimeo
# (see documents.py's transcript dispatch), not a reconstructed watch URL.
_VIMEO = re.compile(r"^https?://(?:www\.)?vimeo\.com/")

_PDF_EXTENSION = re.compile(r"\.pdf(?:[?#]|$)", re.IGNORECASE)
_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "svg")
_IMAGE_EXTENSION = re.compile(
    r"\.(" + "|".join(_IMAGE_EXTENSIONS) + r")(?:[?#]|$)", re.IGNORECASE
)


def classify_url(url: str) -> TargetKind | None:
    """Pre-fetch routing signal from the URL alone -- no network call.

    Returns "transcript" for a recognized youtube/vimeo video URL, "pdf"/"image" for
    a recognizable file extension, or None when nothing fires (the conductor then
    proceeds to fetch and calls `sniff_kind` post-fetch, defaulting to "html").
    """
    if _YT_VIDEO.search(url) or _VIMEO.match(url):
        return "transcript"
    if _PDF_EXTENSION.search(url):
        return "pdf"
    if _IMAGE_EXTENSION.search(url):
        return "image"
    return None


def _sniff_magic_kind(head: bytes) -> TargetKind | None:
    """Byte-sniff `head` via puremagic; None when nothing recognizable matches.

    puremagic.magic_string raises PureValueError on empty input and returns an
    empty list (not an error) when no signature matches -- both are treated the
    same way here: "no opinion", letting the caller fall back to its own default.
    """
    try:
        matches = puremagic.magic_string(head)
    except (puremagic.PureError, ValueError):
        # PureValueError (raised on empty input) subclasses ValueError, not
        # PureError -- catch both so an empty/too-short head is "no opinion"
        # rather than a crash.
        return None
    for match in matches:
        mime = (match.mime_type or "").lower()
        if mime == "application/pdf":
            return "pdf"
        if mime.startswith("image/"):
            return "image"
    return None


def sniff_kind(content_type: str, head: bytes) -> TargetKind:
    """Post-fetch tiebreaker: HTTP Content-Type first, byte-sniff to correct/complete it.

    A decisive, recognized Content-Type (application/pdf, image/*, text/html,
    application/xhtml+xml) is trusted UNLESS the byte-sniff disagrees with a
    positive finding of its own -- the bytes are ground truth (see the T2 brief:
    a .pdf served as application/octet-stream whose bytes start "%PDF-" must route
    to pdf, not html). An ambiguous header (empty, missing, or octet-stream) always
    defers to the byte-sniff. When neither the header nor the bytes yield a kind,
    default to "html" (today's behaviour for an unrecognized response).
    """
    sniffed = _sniff_magic_kind(head)
    if sniffed is not None:
        return sniffed

    normalized = (content_type or "").lower()
    if "pdf" in normalized:
        return "pdf"
    if normalized.startswith("image/"):
        return "image"
    return "html"
