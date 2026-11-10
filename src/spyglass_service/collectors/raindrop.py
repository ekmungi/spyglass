"""Raindrop.io collector: polls bookmarks with a personal test token."""

from datetime import datetime
from urllib.parse import urlparse

import httpx

from spyglass_service.collectors.base import CollectedItem

# Collection 0 means "all bookmarks"; newest first so polling sees recent saves.
_API_URL = "https://api.raindrop.io/rest/v1/raindrops/0"
# Single-bookmark endpoint (singular) for PUT moves; {id} is the raindrop _id.
_RAINDROP_URL = "https://api.raindrop.io/rest/v1/raindrop"
# Collection list endpoint and single-collection create endpoint.
_COLLECTIONS_URL = "https://api.raindrop.io/rest/v1/collections"
_COLLECTION_URL = "https://api.raindrop.io/rest/v1/collection"
# Name of the destination collection for processed (deleted) Raindrop bookmarks.
PROCESSED_COLLECTION = "Processed"
_PER_PAGE = 50  # Raindrop's maximum page size.
_MAX_PAGES = 40  # Safety cap (2000 bookmarks) to avoid an unbounded loop.


class RaindropError(Exception):
    """Raised when the Raindrop API rejects the request or returns a bad payload."""


def _bearer_headers(token: str) -> dict:
    """Return an Authorization header dict for the given Bearer token."""
    return {"Authorization": f"Bearer {token}"}


def resolve_processed_collection(
    token: str, client: httpx.Client | None = None
) -> int:
    """Return the id of the 'Processed' collection, creating it if absent.

    GETs the collections list and looks for a title matching PROCESSED_COLLECTION
    (case-insensitive). If none is found, POSTs to create it. Returns the collection
    _id as an int. Raises RaindropError on any non-200 response.
    """
    http = client or httpx.Client(timeout=20)
    response = http.get(_COLLECTIONS_URL, headers=_bearer_headers(token))
    if response.status_code != 200:
        raise RaindropError(f"Raindrop API returned {response.status_code}")
    items = response.json().get("items", [])
    for col in items:
        if col.get("title", "").lower() == PROCESSED_COLLECTION.lower():
            return int(col["_id"])
    # Collection not found -- create it.
    create_response = http.post(
        _COLLECTION_URL,
        json={"title": PROCESSED_COLLECTION},
        headers=_bearer_headers(token),
    )
    if create_response.status_code != 200:
        raise RaindropError(f"Raindrop API returned {create_response.status_code}")
    return int(create_response.json()["item"]["_id"])


def move_bookmark_to_collection(
    token: str,
    external_id: str,
    collection_id: int,
    client: httpx.Client | None = None,
) -> None:
    """Move one bookmark (external_id) into the given collection via PUT.

    Sends PUT /raindrop/{external_id} with body {"collection": {"$id": collection_id}}
    and a Bearer token. Raises RaindropError on any non-200 response so the caller can
    capture the failure per item without aborting the batch.
    """
    http = client or httpx.Client(timeout=20)
    response = http.put(
        f"{_RAINDROP_URL}/{external_id}",
        json={"collection": {"$id": collection_id}},
        headers=_bearer_headers(token),
    )
    if response.status_code != 200:
        raise RaindropError(f"Raindrop API returned {response.status_code}")


class RaindropCollector:
    """Fetches recent bookmarks; dedupe against the database happens downstream."""

    name = "raindrop"

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(timeout=20)

    def collect(self) -> list[CollectedItem]:
        """Return all bookmarks, newest first, paging until a short page.

        Raises RaindropError on auth failures or unexpected payload shapes so the
        run log records a clear cause instead of a silent empty result.
        """
        raw_items: list[dict] = []
        for page in range(_MAX_PAGES):
            response = self._client.get(
                _API_URL,
                params={"sort": "-created", "perpage": _PER_PAGE, "page": page},
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if response.status_code != 200:
                raise RaindropError(f"Raindrop API returned {response.status_code}")
            payload = response.json()
            if "items" not in payload:
                raise RaindropError("Unexpected Raindrop payload: missing 'items'")
            batch = payload["items"]
            raw_items.extend(batch)
            # A page smaller than the max means we have reached the last page.
            if len(batch) < _PER_PAGE:
                break
        return [self._to_item(raw) for raw in raw_items]

    @staticmethod
    def _to_item(raw: dict) -> CollectedItem:
        """Map one raindrop JSON object to the normalized collected-item shape."""
        created = raw.get("created")
        published = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None
        # The bookmarked site identifies the real source; Raindrop sends it as
        # `domain`, with the link hostname (minus www.) as the fallback.
        host = urlparse(raw.get("link", "")).hostname or None
        origin = raw.get("domain") or (host.removeprefix("www.") if host else None)
        return CollectedItem(
            source="raindrop",
            external_id=str(raw["_id"]),
            title=raw.get("title") or raw.get("link", ""),
            url=raw.get("link", ""),
            summary=raw.get("excerpt") or None,
            source_tags=[str(tag) for tag in raw.get("tags", [])],
            published_at=published,
            origin=origin,
        )
