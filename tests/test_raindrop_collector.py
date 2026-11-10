"""Tests for the Raindrop collector (httpx MockTransport, no network)."""

import json

import httpx
import pytest

from spyglass_service.collectors.raindrop import (
    RaindropCollector,
    RaindropError,
    move_bookmark_to_collection,
    resolve_processed_collection,
)

RAINDROPS_PAGE = {
    "items": [
        {
            "_id": 1001,
            "title": "Local-first sync engines compared",
            "link": "https://example.test/sync",
            "excerpt": "A survey of CRDT-based engines.",
            "created": "2026-06-09T10:00:00.000Z",
        },
        {
            "_id": 1002,
            "title": "EU AI Act explainer",
            "link": "https://example.test/aiact",
            "excerpt": "",
            "created": "2026-06-10T11:30:00.000Z",
        },
    ]
}


def make_client(handler) -> httpx.Client:
    """httpx client whose transport is fully mocked."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_collects_bookmarks_with_bearer_token() -> None:
    """Bookmarks map to collected items; the token travels as a Bearer header."""
    seen_headers: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=RAINDROPS_PAGE)

    collector = RaindropCollector(token="tok-123", client=make_client(handler))
    items = collector.collect()

    assert seen_headers["authorization"] == "Bearer tok-123"
    assert len(items) == 2
    assert {i.source for i in items} == {"raindrop"}
    assert items[0].external_id == "1001"
    assert items[0].url == "https://example.test/sync"


def test_captures_the_site_domain_as_origin() -> None:
    """Bookmarks record WHICH site they point at: Raindrop's domain field, or
    the link hostname when the field is absent."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [
            {"_id": 1, "title": "A", "link": "https://blog.example.org/post", "domain": "blog.example.org"},
            {"_id": 2, "title": "B", "link": "https://www.example.com/paper"},
        ]})

    items = RaindropCollector(token="t", client=make_client(handler)).collect()
    assert items[0].origin == "blog.example.org"
    assert items[1].origin == "example.com"


def test_captures_raindrop_tags() -> None:
    """Raindrop tags travel through for later filtering."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [
            {"_id": 1, "title": "T", "link": "https://x.test", "tags": ["ai", "papers"]},
        ]})

    collector = RaindropCollector(token="t", client=make_client(handler))
    items = collector.collect()
    assert items[0].source_tags == ["ai", "papers"]


def test_invalid_token_raises_a_clear_error() -> None:
    """A 401 from Raindrop becomes a RaindropError naming the cause, not a crash."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"result": False})

    collector = RaindropCollector(token="bad", client=make_client(handler))
    with pytest.raises(RaindropError, match="401"):
        collector.collect()


def test_paginates_until_a_short_page() -> None:
    """More than one page of bookmarks: fetch every page, not just the first 50."""
    pages = {
        0: [{"_id": i, "title": f"T{i}", "link": f"https://x.test/{i}", "created": None}
            for i in range(50)],
        1: [{"_id": 100 + i, "title": f"U{i}", "link": f"https://x.test/u{i}", "created": None}
            for i in range(11)],
    }
    seen_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        seen_pages.append(page)
        return httpx.Response(200, json={"items": pages.get(page, [])})

    collector = RaindropCollector(token="tok", client=make_client(handler))
    items = collector.collect()

    assert len(items) == 61
    assert seen_pages == [0, 1]  # stops after the short second page, no wasted page 2


def test_empty_collection_yields_no_items() -> None:
    """A Raindrop account with no bookmarks is a valid, empty result."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    collector = RaindropCollector(token="tok", client=make_client(handler))
    assert collector.collect() == []


def test_malformed_payload_raises_raindrop_error() -> None:
    """A non-JSON or shape-shifted payload fails loudly, never silently."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"unexpected": True}))

    collector = RaindropCollector(token="tok", client=make_client(handler))
    with pytest.raises(RaindropError, match="payload"):
        collector.collect()


def test_resolve_processed_collection_finds_existing() -> None:
    """GET /collections returns a 'Processed' entry -> its _id is returned; no POST issued."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"items": [
            {"_id": 1, "title": "Inbox"},
            {"_id": 42, "title": "Processed"},
        ]})

    cid = resolve_processed_collection("tok", client=make_client(handler))
    assert cid == 42
    assert calls == ["GET"]


def test_resolve_processed_collection_creates_when_absent() -> None:
    """No 'Processed' collection in the list -> a POST is issued -> new _id is returned."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"_id": 1, "title": "Inbox"}]})
        # POST to create
        return httpx.Response(200, json={"item": {"_id": 456, "title": "Processed"}})

    cid = resolve_processed_collection("tok", client=make_client(handler))
    assert cid == 456
    assert calls == ["GET", "POST"]


def test_move_bookmark_puts_collection_id() -> None:
    """move_bookmark_to_collection issues PUT /raindrop/{id} with Bearer token and collection.$id body."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"item": {"_id": 1001}})

    move_bookmark_to_collection("tok-7", "1001", 42, client=make_client(handler))
    assert seen["method"] == "PUT"
    assert seen["url"].endswith("/raindrop/1001")
    assert seen["auth"] == "Bearer tok-7"
    assert seen["body"] == {"collection": {"$id": 42}}
