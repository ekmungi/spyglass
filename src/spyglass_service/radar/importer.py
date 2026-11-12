"""Import a page the reader already has: from their browser, pasted text or a saved file.

Spyglass never signs in anywhere and never sends cookies, so a subscriber-only article or a page
behind a bot check cannot be fetched by the service. The reader's own browser has the page, and
this module turns what the reader hands over into the item's reader document:

- the item is found or created exactly as a captured link is (`capture.capture_url`, with the
  same address normalisation and de-duplication) and marked as sent in by the reader;
- the reader document is built from the given content with the reader's own extractor and
  sanitiser, and REPLACES any earlier one (typically a failed fetch or a paywalled preview);
- the plain text goes to the Content table so the assessment and the assistant read the full text;
- any earlier judgement is cleared, so the item is judged again on that text.

A page sent from a host other than the one it claims to be from (`Incoming.no_replace`) is the
exception: it can never replace an item the reader already has; and when the sender is also
another site (`Incoming.foreign_sender`), a new item made from it shows the SENDER as its
publication, not the claimed site.

Nothing here touches the network: the address is checked by its form only, and the page title
comes from the content. Only the extracted article body is stored, never the whole page, because
a page from a signed-in session can show the reader's account name in its header or footer.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.content_store import store_fulltext
from spyglass_service.models import Item
from spyglass_service.radar.capture import CaptureError, capture_url, untitled, url_forms, validate_capture_url
from spyglass_service.radar.import_files import (
    ImportRefused,
    check_page_size,
    first_line_title,
    looks_like_html,
    pdf_text,
    text_to_html,
)
from spyglass_service.radar import from_you_store
from spyglass_service.radar.import_image import image_fields, keep_image
from spyglass_service.radar.import_trust import REPLACE_REFUSED
from spyglass_service.radar.models import Assessment, ReaderDoc, utcnow
from spyglass_service.radar.reader.article import count_words, extract_article
from spyglass_service.radar.reader.pdf import pdf_result
from spyglass_service.radar.reader.sanitize import clean_html
from spyglass_service.radar.reader.text import plain_text

__all__ = ["ImportRefused", "Incoming", "find_existing", "import_page", "preview_page",
           "validate_page_url"]

logger = logging.getLogger(__name__)

# Characters of article text shown on the confirmation page.
PREVIEW_CHARS = 600
_PDF_NOTICE = f"{from_you_store.PDF_ADDED}, shown below."
_PDF_NO_TEXT = (f"{from_you_store.PDF_ADDED}, shown below. No text could be read from it (it may be "
                "a scan), so the assistant cannot read it.")


@dataclass(frozen=True)
class Incoming:
    """What the reader hands over: an address and exactly one of a page, text or a PDF.

    `via` is the channel recorded on the item: browser (the bookmark button), paste or file.
    """

    url: str
    title: str = ""
    html: str | None = None
    text: str | None = None
    pdf: bytes | None = None
    # A picture as (bytes, media type), shown by a document made for it (see import_image).
    image: tuple[bytes, str] | None = None
    via: str = "browser"
    # The host of the site that really sent the page when it is not the claimed address's site
    # (approximately); a new item then shows it as its publication.
    foreign_sender: str | None = None
    # Set when the sender's host is not exactly the address's host: the page may not replace an
    # item the reader already has.
    no_replace: bool = False
    # The reader's own words about the page, stored as their note on the item.
    note: str | None = None


def validate_page_url(url: str) -> str:
    """The normalised address, checked by its form only (no lookup); ImportRefused otherwise.

    The same rules as a captured link: http(s) only, no user name or password, and no local,
    private or internal host however it is written.
    """
    try:
        return validate_capture_url(url)
    except CaptureError as exc:
        raise ImportRefused(str(exc)) from exc


def _no_lookup(host: str) -> list[str]:
    """A resolver that refuses, so the shared capture code makes no DNS request for an import."""
    raise OSError("no address lookups while importing")


def preview_page(html: str, url: str) -> dict:
    """What the confirmation page shows: title, word count and the start of the article text.

    The text comes from the reader's extractor and sanitiser and is returned as plain text, so
    nothing of the staged page itself is ever served back.
    """
    article = extract_article(html, url)
    text = plain_text(article["html"]) if article["html"] else ""
    return {"title": article["title"], "site": article["site"],
            "word_count": article["word_count"], "excerpt": text[:PREVIEW_CHARS]}


def find_existing(engine: Engine, url: str) -> int | None:
    """The id of the item already stored for this (normalised) address, or None."""
    forms = url_forms(url)
    with Session(engine) as session:
        row = session.exec(select(Item.id).where(
            Item.url.in_(forms) | Item.external_id.in_(forms)  # type: ignore[attr-defined]
        )).first()
    return row


def _article_fields(html: str, url: str) -> dict:
    """Reader fields of a web page (or HTML source); ImportRefused when nothing is readable."""
    check_page_size(html)
    article = extract_article(html, url)
    body = article["html"] or clean_html(html, url)
    words = article["word_count"] or (count_words(body) if body else 0)
    if not words:
        raise ImportRefused("No readable text was found in this page.")
    return {"kind": "article", "html": body, "title": article["title"], "byline": article["byline"],
            "site": article["site"], "lead_image": article["lead_image"], "word_count": words,
            "source_url": url, "alt_url": None, "text": plain_text(body)}


def _text_fields(text: str, url: str) -> dict:
    """Reader fields of pasted text: HTML source goes through the extractor, prose is escaped."""
    if not text.strip():
        raise ImportRefused("Paste the text of the article first.")
    if looks_like_html(text):
        return _article_fields(text, url)
    check_page_size(text)
    body = clean_html(text_to_html(text), url)
    return {"kind": "article", "html": body, "title": first_line_title(text), "byline": "",
            "site": "", "lead_image": "", "word_count": count_words(body), "source_url": url,
            "alt_url": None, "text": plain_text(body)}


def _pdf_fields(data: bytes, url: str, title: str) -> dict:
    """Reader fields of a PDF: a notice above the built-in viewer, and the PDF's text."""
    text = pdf_text(data)
    fields = pdf_result(url, title or first_line_title(text), "",
                        notice=_PDF_NOTICE if text else _PDF_NO_TEXT, source_url=url)
    return {**fields, "word_count": len(text.split()), "text": text}


def build_document(incoming: Incoming, url: str) -> dict:
    """The reader fields (plus "text") for what was handed over; ImportRefused when unusable."""
    given = [part for part in (incoming.html, incoming.text, incoming.pdf, incoming.image)
             if part is not None]
    if len(given) != 1:
        raise ImportRefused("Send one page, one text or one file at a time.")
    if incoming.image is not None:
        return image_fields(url, incoming.title, incoming.note)
    if incoming.pdf is not None:
        return _pdf_fields(incoming.pdf, url, incoming.title.strip())
    if incoming.text is not None:
        return _text_fields(incoming.text, url)
    return _article_fields(incoming.html or "", url)


def _keep_pdf(data_dir: Path, item_id: int, data: bytes) -> None:
    """Put the PDF in the store of files the reader sent in, where the built-in viewer reads it.

    It is not a copy of a web page (it cannot be downloaded again), so it is kept apart from the PDF
    cache, which is trimmed to a size limit.
    """
    from_you_store.put(data_dir, item_id, data)


def _store_document(engine: Engine, item_id: int, fields: dict, title: str) -> None:
    """Replace the item's reader document, clear its judgement and give it a title if it has none."""
    with Session(engine) as session:
        row = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first()
        row = row or ReaderDoc(item_id=item_id)
        row.kind, row.html = fields["kind"], fields["html"]
        row.title = fields.get("title") or title or None
        row.byline, row.site = fields.get("byline") or None, fields.get("site") or None
        row.lead_image = fields.get("lead_image") or None
        row.word_count = int(fields.get("word_count") or 0)
        row.source_url, row.alt_url = fields.get("source_url"), fields.get("alt_url")
        row.status, row.error, row.fetched_at = "ok", None, utcnow()
        session.add(row)
        judged = session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()
        if judged is not None:
            session.delete(judged)
        item = session.get(Item, item_id)
        if item is not None and title and item.title == untitled(item.url):
            item.title = title
            session.add(item)
        session.commit()


def _set_publication(engine: Engine, item_id: int, publication: str) -> None:
    """Show `publication` as the item's publication (the site that really sent the page)."""
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is not None:
            item.origin = publication[:200]
            session.add(item)
            session.commit()


def import_page(engine: Engine, settings, incoming: Incoming) -> int:
    """Import what the reader handed over and return the item id.

    Raises ImportRefused (with a sentence fit for the reader) for an address that is not public
    http(s) or content with nothing readable in it; nothing is stored in that case.
    """
    url = validate_page_url(incoming.url)
    if incoming.no_replace and find_existing(engine, url) is not None:
        raise ImportRefused(REPLACE_REFUSED)
    fields = build_document(incoming, url)
    if incoming.foreign_sender:
        fields = {**fields, "site": incoming.foreign_sender}
    title = (incoming.title.strip() or fields.get("title") or "")[:500]
    try:
        item_id = capture_url(engine, settings, url, note=incoming.note, via=incoming.via,
                              title_fetch=lambda _url: title or None, resolver=_no_lookup)
    except CaptureError as exc:
        raise ImportRefused(str(exc)) from exc
    if incoming.pdf is not None:
        _keep_pdf(Path(settings.data_dir), item_id, incoming.pdf)
    if incoming.image is not None:
        keep_image(Path(settings.data_dir), item_id, incoming.image[0])
    text = fields.pop("text", "")
    _store_document(engine, item_id, fields, title)
    if incoming.foreign_sender:
        _set_publication(engine, item_id, incoming.foreign_sender)
    if text.strip():
        store_fulltext(engine, item_id=item_id, markdown=text, source_url=url,
                       content_type=("application/pdf" if incoming.pdf is not None else
                                     incoming.image[1] if incoming.image is not None else "text/html"),
                       status="ok", detected_type=f"import:{fields['kind']}")
    logger.info("imported item %s via %s (%s words)", item_id, incoming.via, fields["word_count"])
    return item_id
