"""The assessment's fallback fetch: the engine's ladder, guarded against private addresses."""

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.content_routing import classify_url
from spyglass_service.content_store import store_fulltext
from spyglass_service.fetch_rungs import build_rungs
from spyglass_service.models import Item
from spyglass_service.radar.netguard import guard_client, is_public_url


def plain_fetch(engine: Engine, settings, item_id: int) -> None:
    """Fetch the item's URL with the engine ladder, refusing non-public addresses.

    A link from a feed could point at this computer or a private network, so the address is
    checked before the request, every redirect hop is checked by the guarded client and the
    guarded curl_cffi rung, and the final address is checked again before the text is kept.
    A refused address is stored as a failed Content row; the digest then uses the feed snippet.
    """
    from spyglass_service.documents import build_client, fetch_fulltext

    with Session(engine) as session:
        item = session.get(Item, item_id)
        url = item.url if item else None
    if not url:
        return

    def refuse() -> None:
        """Store a failed row so the digest falls back to the feed snippet."""
        store_fulltext(engine, item_id=item_id, markdown="", status="failed",
                       error="The address is not a public web address.", error_class="blocked")

    if not is_public_url(url):
        return refuse()
    client = guard_client(build_client())
    try:
        fetched = fetch_fulltext(
            url, client=client, settings=settings, engine=engine,
            acquire_rungs=build_rungs(settings, classify_url(url) or "html", guarded=True))
    finally:
        client.close()
    final = fetched.get("source_url")
    if final and final != url and not is_public_url(final):
        return refuse()
    store_fulltext(
        engine, item_id=item_id, markdown=fetched.get("markdown") or "",
        source_url=final, content_type=fetched.get("content_type"),
        status=fetched.get("status", "failed"), error=fetched.get("error"),
        detected_type=fetched.get("detected_type"), tier_reached=fetched.get("tier_reached"),
        http_status=fetched.get("http_status"), error_class=fetched.get("error_class"),
    )
