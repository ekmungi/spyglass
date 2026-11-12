"""Files and pictures posted in the Slack capture channel become items under "From you".

For each file of a message the capture channel receives (by the timer route or the live
connection, which both call `import_message_files`):

1. its description is completed when Slack sent only a stub (`files.info`);
2. the type is judged from the name, Slack's own type fields and, after the download, the bytes:
   PDF, PNG, JPEG, WebP, plain text and Markdown are accepted, nothing else (SVG and HTML are not);
3. the file is downloaded with the bot token, which goes only to Slack's file host: the address
   must be https on `files.slack.com` for every request, including each redirect hop, and the
   download is cut off at 20 MB. A file Slack declares larger is not downloaded at all;
4. it is imported through the same code as the "add file" button (`importer.import_page`): a PDF
   as a readable document with its text, text as a document, and a picture as an item whose
   document shows it, the bytes kept in the image store. The item is sent in by the reader through
   Slack, carries the message text as the reader's note, and is judged at once.

A file that cannot be imported (too large, another type, deleted, or refused by Slack) still
becomes an item, with the file's name and one plain sentence saying why. A passing failure (Slack
down, a timeout) raises `SlackFileTransient` instead, and the caller leaves the message to be read
again; reading it again finds the same items, never duplicates. Downloading needs the Slack scope
`files:read`; without it Slack answers with a sign-in page, which is reported in those words.
"""

import logging
from collections.abc import Callable
from pathlib import PurePath
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import Engine

from spyglass_service.radar import netguard
from spyglass_service.radar.egress import SecretDestinationError, api_client, assert_secret_destination
from spyglass_service.radar.import_files import ImportRefused
from spyglass_service.radar.import_image import IMAGE_TYPES
from spyglass_service.radar.importer import Incoming, import_page
from spyglass_service.radar.text_clean import clean_line

logger = logging.getLogger(__name__)

MAX_FILE_MB = 20
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
# The only host the bot token is sent to when downloading (the Web API at slack.com is separate).
FILE_HOST = "files.slack.com"
INFO_URL = "https://slack.com/api/files.info"
# Redirects followed by hand, each one checked before it is requested.
MAX_HOPS = 3
DOWNLOAD_TIMEOUT = 60.0
ACCEPTED = "PDF, PNG, JPEG, WebP, plain text and Markdown"
SCOPE_HINT = "the Slack app needs the files:read permission"

_BY_EXTENSION = {".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp",
                 ".txt": "text", ".md": "text", ".markdown": "text"}
_BY_MIMETYPE = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpeg",
                "image/webp": "webp", "text/plain": "text", "text/markdown": "text"}
_BY_FILETYPE = {"pdf": "pdf", "png": "png", "jpg": "jpeg", "jpeg": "jpeg", "webp": "webp",
                "text": "text", "markdown": "text"}
_LABELS = {"pdf": "PDF", "png": "PNG picture", "jpeg": "JPEG picture", "webp": "WebP picture",
           "text": "text file"}

# (address) -> the file's bytes; raises SlackFileRefused or SlackFileTransient.
Download = Callable[[str], bytes]
# (Web API address, parameters) -> decoded JSON answer.
Api = Callable[[str, dict], dict]


class SlackFileRefused(Exception):
    """The file cannot be imported; the message is one plain sentence for the reader."""


class SlackFileTransient(Exception):
    """The download failed for a passing reason (Slack or the network); try the message again."""


def file_kind(name: str, mimetype: str, filetype: str) -> str | None:
    """"pdf", "png", "jpeg", "webp" or "text" for an accepted file; None for anything else."""
    extension = PurePath(name or "").suffix.lower()
    if extension in _BY_EXTENSION:
        return _BY_EXTENSION[extension]
    return _BY_MIMETYPE.get((mimetype or "").lower()) or _BY_FILETYPE.get((filetype or "").lower())


def looks_like(kind: str, data: bytes) -> bool:
    """True when the bytes have the signature of `kind` (text: no NUL byte in the first 8 KB)."""
    if kind == "pdf":
        return b"%PDF-" in data[:1024]
    if kind == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if kind == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return kind == "text" and b"\x00" not in data[:8192]


def _check_address(url: str) -> None:
    """Refuse any address but https on the Slack file host (the token must not go elsewhere)."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "https" or (parts.hostname or "").lower() != FILE_HOST or port not in (None, 443):
        raise SlackFileRefused("That is not a Slack file address.")
    try:
        assert_secret_destination("slack_bot_token", url)
    except SecretDestinationError as exc:
        raise SlackFileRefused("That is not a Slack file address.") from exc
    reach = netguard.check_url(url)
    if reach is netguard.Reach.UNRESOLVED:
        raise SlackFileTransient(netguard.UNREACHABLE)
    if reach is not netguard.Reach.PUBLIC:
        raise SlackFileRefused("That is not a Slack file address.")


def _read_body(response: httpx.Response) -> bytes:
    """The body of an answer that passed the status checks, cut off at the size limit."""
    too_big = SlackFileRefused(f"The file is larger than {MAX_FILE_MB} MB.")
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise too_big
    if response.headers.get("content-type", "").lower().startswith("text/html"):
        raise SlackFileRefused(f"Slack sent a sign-in page instead of the file; {SCOPE_HINT}.")
    chunks, total = [], 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)


def make_downloader(token: str, *, http_transport: httpx.BaseTransport | None = None) -> Download:
    """A function that downloads one Slack file with `token`, under the rules in the module doc.

    The client is the service-API one (`egress.api_client`), which checks on every request that the
    token is bound for that host and never follows a redirect by itself; redirects are followed
    here, one hop at a time, each address checked before it is requested. `http_transport` is for
    tests.
    """
    def download(url: str) -> bytes:
        """The bytes of the file at `url`."""
        current = url
        try:
            with api_client("slack_bot_token", timeout=DOWNLOAD_TIMEOUT, transport=http_transport) as client:
                for _hop in range(MAX_HOPS + 1):
                    _check_address(current)
                    with client.stream("GET", current,
                                       headers={"Authorization": f"Bearer {token}"}) as response:
                        status = response.status_code
                        if status in (301, 302, 303, 307, 308) and response.headers.get("location"):
                            current = urljoin(current, response.headers["location"])
                            continue
                        _raise_for_status(status)
                        return _read_body(response)
        except SecretDestinationError as exc:
            raise SlackFileRefused("That is not a Slack file address.") from exc
        except httpx.HTTPError as exc:
            raise SlackFileTransient(netguard.UNREACHABLE) from exc
        raise SlackFileRefused("Slack redirected the download too many times.")

    return download


def _raise_for_status(status: int) -> None:
    """Turn a non-200 answer into a refusal (a permanent reason) or a passing failure."""
    if status == 200:
        return
    if status in (401, 403):
        raise SlackFileRefused(f"Slack would not give Spyglass the file; {SCOPE_HINT}.")
    if status in (404, 410):
        raise SlackFileRefused("The file is no longer available in Slack.")
    if status == 429 or status >= 500:
        raise SlackFileTransient("Slack did not answer; the message will be read again.")
    raise SlackFileRefused(f"Slack answered HTTP {status} for the file.")


def _described(raw: dict, api: Api | None) -> dict:
    """The file's full description: a stub Slack sent for a shared file is looked up first."""
    if raw.get("file_access") != "check_file_info" or not raw.get("id"):
        return raw
    if api is None:
        raise SlackFileRefused("Spyglass needs the Slack bot token to look the file up.")
    try:
        answer = api(INFO_URL, {"file": raw["id"]})
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise SlackFileTransient("Slack did not answer.") from exc
    file = answer.get("file") if isinstance(answer, dict) else None
    if not (isinstance(answer, dict) and answer.get("ok") and isinstance(file, dict)):
        error = clean_line((answer or {}).get("error") if isinstance(answer, dict) else "", 40)
        raise SlackFileRefused(f"Slack would not describe the file ({error or 'no reason given'}).")
    return file


def _fetch(file: dict, download: Download | None) -> tuple[str, bytes]:
    """(kind, bytes) of an acceptable file; SlackFileRefused with the reason otherwise."""
    name = clean_line(file.get("name") or file.get("title"), 200)
    kind = file_kind(name, str(file.get("mimetype") or ""), str(file.get("filetype") or ""))
    if kind is None:
        label = clean_line(file.get("filetype") or PurePath(name).suffix.lstrip(".") or "unknown", 20)
        raise SlackFileRefused(f"Only {ACCEPTED} files are imported; this one is a {label} file.")
    size = file.get("size")
    if isinstance(size, int) and size > MAX_FILE_BYTES:
        raise SlackFileRefused(f"The file is larger than {MAX_FILE_MB} MB.")
    url = str(file.get("url_private_download") or file.get("url_private") or "")
    if file.get("mode") == "external" or not url:
        raise SlackFileRefused("The file is kept outside Slack, so Spyglass cannot download it.")
    if download is None:
        raise SlackFileRefused(
            "Spyglass needs the Slack bot token, with the files:read permission, to download files.")
    data = download(url)
    if not data:
        raise SlackFileRefused("The file is empty.")
    if not looks_like(kind, data):
        raise SlackFileRefused(f"The file does not look like a {_LABELS[kind]}, so it was not stored.")
    return kind, data


def _incoming(kind: str, data: bytes, url: str, name: str, note: str | None) -> Incoming:
    """What `import_page` is given for an accepted file."""
    if kind == "pdf":
        return Incoming(url=url, title=name, pdf=data, via="slack", note=note)
    if kind == "text":
        return Incoming(url=url, title=name, text=data.decode("utf-8", "replace"), via="slack", note=note)
    return Incoming(url=url, title=name, image=(data, IMAGE_TYPES[kind]), via="slack", note=note)


def _address_of(file: dict) -> str | None:
    """The file's own web address in Slack (its permalink), or a stand-in made from its id."""
    link = str(file.get("permalink") or "")
    if link:
        return link
    return f"https://slack.com/files/{file['id']}" if file.get("id") else None


def _is_empty_stub(raw: dict) -> bool:
    """True for an entry that describes nothing worth recording: a deleted file or a bare id."""
    if raw.get("mode") == "tombstone" or raw.get("file_access") == "file_not_found":
        return True
    named = raw.get("name") or raw.get("title") or raw.get("url_private_download") or raw.get("permalink")
    return not named and raw.get("file_access") != "check_file_info"


def _import_one(engine: Engine, settings, raw: dict, note: str | None, download: Download | None,
                api: Api | None) -> int | None:
    """Import one file, or record why not; the item id, or None when there is nothing to record."""
    if _is_empty_stub(raw):
        return None
    file = raw
    try:
        file = _described(raw, api)
        kind, data = _fetch(file, download)
        url, name = _address_of(file), clean_line(file.get("name") or file.get("title"), 200)
        if url is None:
            return None
        return import_page(engine, settings, _incoming(kind, data, url, name or "Slack file", note))
    except (SlackFileRefused, ImportRefused) as exc:
        reason = str(exc)
    url, name = _address_of(file) or _address_of(raw), clean_line(
        file.get("name") or file.get("title") or raw.get("name"), 200)
    if url is None:
        logger.info("a Slack file with no address was skipped: %s", reason)
        return None
    sentence = f"{name or 'The file'} was not imported: {reason}"
    try:
        return import_page(engine, settings, Incoming(url=url, title=name or "Slack file",
                                                      text=sentence, via="slack", note=note))
    except ImportRefused as exc:
        logger.info("a Slack file could not even be recorded (%s)", exc)
        return None


def import_message_files(engine: Engine, settings, message: dict, *, note: str | None,
                         token: str | None, download: Download | None = None,
                         api: Api | None = None,
                         http_transport: httpx.BaseTransport | None = None) -> list[int]:
    """Import every file of a Slack message; returns the item ids, in the order of the files.

    `note` is the message text, kept as the reader's note on each item. `download` and `api`
    replace the real downloader and Web API call (tests); by default both use `token`, and with no
    token every file is recorded with the reason. Raises `SlackFileTransient` for a passing
    failure, after which the caller must not mark the message as handled.
    """
    files = [f for f in (message.get("files") or []) if isinstance(f, dict)]
    if not files:
        return []
    if download is None and token:
        download = make_downloader(token, http_transport=http_transport)
    if api is None and token:
        from spyglass_service.radar.sources.slack import _http_transport  # here: it imports this module

        api = _http_transport(token)
    ids = []
    for raw in files:
        item_id = _import_one(engine, settings, raw, note, download, api)
        if item_id is not None:
            ids.append(item_id)
    return ids
