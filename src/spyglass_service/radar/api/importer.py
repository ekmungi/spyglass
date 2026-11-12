"""Import API: bring in a page the reader has open in their browser, pasted text or a saved file.

GET  /import/button-key            the bookmark button's secret (same-origin only; the settings page)
POST /import/button-key/rotate     make a new secret, which stops every older button
POST /import/stage                 park a page sent by the "Send to Spyglass" bookmark button
GET  /import/staged/{token}        the confirmation page's preview (sanitised text only)
POST /import/staged/{token}/accept import the parked page
DELETE /import/staged/{token}      discard it
POST /import/text                  import pasted text (JSON)
POST /import/file                  import a saved .pdf, .html or .mhtml file (multipart)

`/import/stage` is the one route another site may post to: the bookmark button's fallback is an
ordinary form submitted from the page the reader is reading. It only parks the page in the bounded
staging area and answers with a redirect to a fixed address on this service (the confirmation
page); it imports nothing and fetches nothing. Every other route here is same-origin only.

Because any site can post there, staging needs the button's secret (`import_key`) and, on the form
path, a real `Origin` header. The sender's origin is kept with the page; when it is not the site the
page claims to be from, the preview says so and the page cannot replace an item the reader already
has (see `import_trust`).
"""

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from spyglass_service.radar.import_files import MAX_FILE_BYTES, MAX_FILE_MB, file_kind, page_from_file
from spyglass_service.radar.import_key import button_key, key_matches, rotate_button_key
from spyglass_service.radar.import_staging import MAX_HTML_BYTES, PageTooLarge, StagingArea, StagingError
from spyglass_service.radar.import_trust import REPLACE_REFUSED, foreign_sender, host_of, may_replace
from spyglass_service.radar.importer import (
    ImportRefused,
    Incoming,
    find_existing,
    import_page,
    preview_page,
    validate_page_url,
)
from spyglass_service.radar.serialize import radar_items
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)

router = APIRouter()

# Body limits, checked while the body is read. A form adds a little framing to a 6 MB page; JSON
# escaping can nearly double markup full of quotes and backslashes.
STAGE_FORM_BYTES = MAX_HTML_BYTES + 256 * 1024
STAGE_JSON_BYTES = 2 * MAX_HTML_BYTES + 256 * 1024
FILE_FORM_BYTES = MAX_FILE_BYTES + 256 * 1024
TEXT_JSON_BYTES = 2 * MAX_HTML_BYTES + 64 * 1024
# The confirmation page; the only place the form transport ever redirects to.
IMPORT_PAGE = "/#/import"
_REFUSAL = "cross-site request refused"
_GONE = "This page is no longer waiting. Send it again from your browser."
_BAD_KEY = "This Send to Spyglass button is out of date. Make a new button in Settings."


class _TooLarge(MultiPartException):
    """The request body passed its limit (a MultiPartException, so the parser closes its files)."""


class StageBody(BaseModel):
    """JSON body of POST /import/stage, sent by the confirmation page after a postMessage."""

    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=2000)
    html: str = Field(min_length=1)
    # The origin of the page that sent the message; shown to the reader, never trusted.
    sender: str | None = Field(default=None, max_length=300)
    # The button's secret, as carried in the message (checked against the saved one).
    key: str = Field(default="", max_length=100)


class TextBody(BaseModel):
    """JSON body of POST /import/text."""

    url: str = Field(min_length=1, max_length=2048)
    text: str = Field(min_length=1, max_length=MAX_HTML_BYTES)
    title: str | None = Field(default=None, max_length=500)


def same_origin_only(request: Request) -> None:
    """Refuse a browser request that says it came from any other site, same-site ones included."""
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if site and site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail=_REFUSAL)


def _area(request: Request) -> StagingArea:
    """The staging area under the service's data folder."""
    return StagingArea(Path(request.app.state.settings.data_dir) / "import_staging")


async def _capped(request: Request, limit: int):
    """The request body in chunks, stopping with _TooLarge once it passes `limit` bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _TooLarge("body too large")
    seen = 0
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > limit:
            raise _TooLarge("body too large")
        yield chunk


async def _read_form(request: Request, limit: int, *, files: int) -> FormData:
    """Parse a multipart body of at most `limit` bytes with at most `files` file parts."""
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="send the body as multipart/form-data")
    parser = MultiPartParser(request.headers, _capped(request, limit), max_files=files,
                             max_fields=8, max_part_size=limit)
    return await parser.parse()


def _field(form: FormData, name: str) -> str:
    """A text field of a form ("" when missing or when a file was sent in its place)."""
    value = form.get(name)
    return value if isinstance(value, str) else ""


def _origin(value: str | None) -> str | None:
    """`scheme://host[:port]` of an http(s) origin, or None for "null", empty or anything else."""
    parts = urlsplit((value or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc}"[:200]


def _to_import_page(**query: str) -> RedirectResponse:
    """A 303 to the confirmation page; the query holds only a token or a fixed error code."""
    text = "&".join(f"{key}={value}" for key, value in query.items())
    return RedirectResponse(f"{IMPORT_PAGE}?{text}", status_code=303)


async def _stage_form(request: Request, area: StagingArea) -> Response:
    """Stage a page posted by the bookmark button's hidden form; always redirects."""
    origin = _origin(request.headers.get("origin"))
    if origin is None:  # no Origin header, or "null": the sender cannot be named
        return _to_import_page(error="origin")
    try:
        form = await _read_form(request, STAGE_FORM_BYTES, files=0)
    except _TooLarge:
        return _to_import_page(error="size")
    except MultiPartException:
        return _to_import_page(error="form")
    if not key_matches(request.app.state.settings.data_dir, _field(form, "key")):
        return _to_import_page(error="key")
    try:
        url = validate_page_url(_field(form, "url"))
    except ImportRefused:
        return _to_import_page(error="address")
    try:
        token = await run_in_threadpool(area.stage, url, _field(form, "title"), _field(form, "html"),
                                        origin)
    except StagingError as exc:
        return _to_import_page(error="size" if isinstance(exc, PageTooLarge) else "empty")
    return _to_import_page(token=token)


async def _stage_json(request: Request, area: StagingArea) -> dict:
    """Stage a page the confirmation page received by postMessage; returns the token."""
    same_origin_only(request)
    chunks = []
    try:
        async for chunk in _capped(request, STAGE_JSON_BYTES):
            chunks.append(chunk)
    except _TooLarge as exc:
        raise HTTPException(status_code=413, detail="The page is larger than 6 MB.") from exc
    try:
        body = StageBody.model_validate(json.loads(b"".join(chunks)))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="The page could not be read.") from exc
    if not key_matches(request.app.state.settings.data_dir, body.key):
        raise HTTPException(status_code=403, detail=_BAD_KEY)
    try:
        url = validate_page_url(body.url)
    except (ValueError, ValidationError) as exc:
        detail = str(exc) if isinstance(exc, ImportRefused) else "The page could not be read."
        raise HTTPException(status_code=400, detail=detail) from exc
    try:
        token = await run_in_threadpool(area.stage, url, body.title, body.html, _origin(body.sender))
    except StagingError as exc:
        status = 413 if isinstance(exc, PageTooLarge) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"token": token}


@router.get("/import/button-key", dependencies=[Depends(same_origin_only)])
def get_button_key(request: Request) -> dict:
    """The bookmark button's secret, for the settings page to build the button with."""
    return {"key": button_key(request.app.state.settings.data_dir)}


@router.post("/import/button-key/rotate", dependencies=[Depends(same_origin_only)])
def new_button_key(request: Request) -> dict:
    """Make a new secret; buttons built with the old one can no longer stage pages."""
    return {"key": rotate_button_key(request.app.state.settings.data_dir)}


@router.post("/import/stage", response_model=None)
async def stage(request: Request) -> Response | dict:
    """Park a page handed over from the reader's browser; nothing is imported yet."""
    content_type = request.headers.get("content-type", "").lower()
    area = _area(request)
    if content_type.startswith("multipart/form-data"):
        return await _stage_form(request, area)
    if content_type.startswith("application/json"):
        return await _stage_json(request, area)
    raise HTTPException(status_code=415, detail="send the page as JSON or multipart/form-data")


@router.get("/import/staged/{token}", dependencies=[Depends(same_origin_only)])
def staged_preview(request: Request, token: str) -> dict:
    """What the confirmation page shows: where the page is from, its title and its first words."""
    try:
        page = _area(request).peek(token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_GONE) from exc
    preview = preview_page(page.html, page.url)
    existing = find_existing(request.app.state.engine, page.url)
    return {
        "token": token, "url": page.url, "host": urlsplit(page.url).hostname or "",
        "title": page.title or preview["title"], "site": preview["site"],
        "word_count": preview["word_count"], "excerpt": preview["excerpt"],
        # Who really sent the page (a host, or null when unknown) and whether that is the site the
        # page says it is from; a page from another site cannot replace an existing item.
        "sender": host_of(page.sender), "sender_matches": foreign_sender(page.sender, page.url) is None,
        "existing_item_id": existing, "replaces_existing": existing is not None,
        # The strict test (exact host) the service applies before replacing anything.
        "replace_refused": existing is not None and not may_replace(page.sender, page.url),
    }


def _kick(request: Request) -> None:
    """Ask for the item to be judged now rather than at the next collection."""
    scheduler = getattr(request.app.state, "radar_scheduler", None)
    if scheduler is not None:
        scheduler.kick_assessment()


def _finish(request: Request, incoming: Incoming) -> dict:
    """Import, ask for analysis and return the RadarItem; ImportRefused becomes a 400."""
    engine = request.app.state.engine
    try:
        item_id = import_page(engine, request.app.state.settings, incoming)
    except ImportRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _kick(request)
    with Session(engine) as session:
        items = radar_items(session, [item_id])
    if not items:
        raise HTTPException(status_code=500, detail="the page was saved but could not be read back")
    return items[0]


@router.post("/import/staged/{token}/accept", dependencies=[Depends(same_origin_only)])
def accept_staged(request: Request, token: str) -> dict:
    """Import a parked page (once: the token is used up); returns the RadarItem.

    A page whose sender is not exactly the host it claims is refused (409, and left waiting) when
    the item already exists; a new item from another site is imported under the sender's name.
    """
    area = _area(request)
    try:
        waiting = area.peek(token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_GONE) from exc
    foreign = foreign_sender(waiting.sender, waiting.url)
    strict = not may_replace(waiting.sender, waiting.url)
    if strict and find_existing(request.app.state.engine, waiting.url) is not None:
        raise HTTPException(status_code=409, detail=REPLACE_REFUSED)
    try:
        page = area.take(token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_GONE) from exc
    return _finish(request, Incoming(url=page.url, title=page.title, html=page.html, via="browser",
                                     foreign_sender=foreign, no_replace=strict))


@router.delete("/import/staged/{token}", status_code=204, dependencies=[Depends(same_origin_only)])
def discard_staged(request: Request, token: str) -> Response:
    """Throw a parked page away."""
    if not _area(request).discard(token):
        raise HTTPException(status_code=404, detail=_GONE)
    return Response(status_code=204)


@router.post("/import/text", dependencies=[Depends(same_origin_only), Depends(require_json)])
def import_text(request: Request, body: TextBody) -> dict:
    """Import pasted text (plain text or copied HTML) as the reader document of an address."""
    return _finish(request, Incoming(url=body.url, title=body.title or "", text=body.text, via="paste"))


@router.post("/import/file", dependencies=[Depends(same_origin_only)])
async def import_file(request: Request) -> dict:
    """Import a saved .pdf, .html or .mhtml file as the reader document of an address."""
    try:
        form = await _read_form(request, FILE_FORM_BYTES, files=1)
    except _TooLarge as exc:
        raise HTTPException(status_code=413, detail=f"The file is larger than {MAX_FILE_MB} MB.") from exc
    except MultiPartException as exc:
        raise HTTPException(status_code=400, detail="The file could not be read.") from exc
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=400, detail="Choose a file to add.")
    data = await upload.read()
    await form.close()
    url, title, name = _field(form, "url"), _field(form, "title"), upload.filename or ""
    return await run_in_threadpool(_import_upload, request, url, title, name, data)


def _import_upload(request: Request, url: str, title: str, name: str, data: bytes) -> dict:
    """Decode an uploaded file and import it (runs in a worker thread)."""
    try:
        kind = file_kind(name, data)
        content = {"pdf": data} if kind == "pdf" else {"html": page_from_file(name, data)}
    except ImportRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _finish(request, Incoming(url=url, title=title, via="file", **content))
