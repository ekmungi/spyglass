"""Direct import API: the "Send to Spyglass" browser extension posts a page or a selection here.

POST /import/direct          import the page or selection in one step (no confirmation window)
GET  /import/direct/check    answer {"ok": true} to a caller that holds the right key

Both routes need the per-install key (the same one the bookmark button uses) in the header
`X-Spyglass-Key`. The key is the protection of the POST: `CROSS_SITE_EXEMPT` in `request_guards`
lets this one route through the cross-site guard, because an extension's requests carry a
`chrome-extension://` origin. A web page still cannot use it, for three independent reasons: it
does not know the key; a custom header makes the browser ask for approval first (a CORS
preflight), which the service refuses for any site but Obsidian and local pages; and this module
refuses any `http(s)` page origin that is not local.

The extension's own requests need no CORS approval: an extension's background script may call the
hosts listed in its manifest. The service's CORS setting is therefore unchanged.

Because the confirmation window is skipped, at most 30 imports are accepted in 10 minutes. Each
import is logged as one line without content (item id, host, word count).
"""

import json
import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError

from spyglass_service import __version__
from spyglass_service.radar.import_direct import (
    MAX_NOTE_CHARS,
    MAX_TEXT_BYTES,
    MAX_TITLE_CHARS,
    RateLimiter,
    import_direct,
)
from spyglass_service.radar.import_files import ImportRefused
from spyglass_service.radar.import_key import key_matches
from spyglass_service.radar.import_staging import MAX_HTML_BYTES
from spyglass_service.request_guards import REFUSAL, origin_allowed

logger = logging.getLogger(__name__)

router = APIRouter()

# JSON escaping can nearly double markup full of quotes and backslashes, plus a little framing.
BODY_LIMIT = 2 * MAX_HTML_BYTES + 256 * 1024
_BAD_KEY = "The key is missing or wrong."
_TOO_MANY = "Too many pages were sent in a short time. Wait a few minutes and try again."
_UNREADABLE = "The page could not be read."
# The origin a browser puts on a request made by an extension's own script.
_EXTENSION_ORIGIN = re.compile(r"[a-z]+-extension://[A-Za-z0-9._-]{1,64}")
_LIMITER_ATTRIBUTE = "direct_import_limiter"


class DirectBody(BaseModel):
    """JSON body of POST /import/direct. Exactly one of `html` and `text` must be given."""

    url: str
    title: str = ""
    html: str | None = None
    text: str | None = None
    note: str | None = None
    kind: str = "page"


def require_key(request: Request) -> None:
    """Refuse a request from a web page, or without the right `X-Spyglass-Key` header (403).

    The answer never says whether the key was close.
    """
    origin = request.headers.get("origin")
    if origin is not None and not (_EXTENSION_ORIGIN.fullmatch(origin) or origin_allowed(origin)):
        raise HTTPException(status_code=403, detail=REFUSAL)
    if not key_matches(request.app.state.settings.data_dir, request.headers.get("x-spyglass-key")):
        raise HTTPException(status_code=403, detail=_BAD_KEY)


def _limiter(request: Request) -> RateLimiter:
    """The app's import rate limiter (created on first use)."""
    state = request.app.state
    if getattr(state, _LIMITER_ATTRIBUTE, None) is None:
        setattr(state, _LIMITER_ATTRIBUTE, RateLimiter())
    return getattr(state, _LIMITER_ATTRIBUTE)


async def _read_body(request: Request) -> bytes:
    """The request body, refusing with 413 as soon as it passes `BODY_LIMIT` bytes."""
    declared = request.headers.get("content-length", "")
    too_large = HTTPException(status_code=413, detail="The page is larger than 6 MB.")
    if declared.isdigit() and int(declared) > BODY_LIMIT:
        raise too_large
    chunks: list[bytes] = []
    seen = 0
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > BODY_LIMIT:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(raw: bytes) -> DirectBody:
    """The validated body; 400 with a plain sentence for anything malformed or over a limit."""
    try:
        body = DirectBody.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=_UNREADABLE) from exc
    if body.kind not in ("page", "selection"):
        raise HTTPException(status_code=400, detail=_UNREADABLE)
    if (body.html is None) == (body.text is None):
        raise HTTPException(status_code=400, detail="Send one page or one text at a time.")
    if len(body.title) > MAX_TITLE_CHARS:
        raise HTTPException(status_code=400, detail=f"The title is longer than {MAX_TITLE_CHARS} characters.")
    if body.note is not None and len(body.note) > MAX_NOTE_CHARS:
        raise HTTPException(status_code=400, detail=f"The note is longer than {MAX_NOTE_CHARS} characters.")
    if body.html is not None and len(body.html.encode("utf-8", "surrogatepass")) > MAX_HTML_BYTES:
        raise HTTPException(status_code=413, detail="The page is larger than 6 MB.")
    if body.text is not None and len(body.text.encode("utf-8", "surrogatepass")) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=413, detail="The selected text is larger than 2 MB.")
    return body


def _import(request: Request, body: DirectBody) -> dict:
    """Import in a worker thread, ask for analysis now and log one line; ImportRefused becomes a 400."""
    try:
        result = import_direct(
            request.app.state.engine, request.app.state.settings, url=body.url, title=body.title,
            html=body.html, text=body.text, note=(body.note or "").strip() or None, kind=body.kind)
    except ImportRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler = getattr(request.app.state, "radar_scheduler", None)
    if scheduler is not None:
        scheduler.kick_assessment()
    logger.info("direct import: item %s from %s, %s words%s", result["item_id"],
                urlsplit(body.url).hostname or "?", result["words"], ", replaced" if result["replaced"] else "")
    return result


@router.get("/import/direct/check", dependencies=[Depends(require_key)])
def check() -> dict:
    """Tell the extension's "Test connection" button that the address and the key are right."""
    return {"ok": True, "app": "spyglass", "version": __version__}


@router.post("/import/direct", dependencies=[Depends(require_key)])
async def direct(request: Request) -> dict:
    """Import a page or a selection the reader sent from their browser; returns the item."""
    if not _limiter(request).allow():
        raise HTTPException(status_code=429, detail=_TOO_MANY)
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        raise HTTPException(status_code=415, detail="send the body as application/json")
    body = _parse(await _read_body(request))
    return await run_in_threadpool(_import, request, body)
