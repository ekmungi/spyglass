"""Tests for the Hacker News and community-papers collectors (fetch injected)."""

import json

import pytest
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.ingest import store_items
from spyglass_service.models import Item
from spyglass_service.radar.models import ItemExtra, loads
from spyglass_service.radar.sources.hackernews import (
    collect_hackernews,
    fetch_stories,
    parse_hits,
)
from spyglass_service.radar.sources.hf_papers import collect_hf_papers, parse_papers

from .test_sources_support import all_items, make_engine, make_settings

HN = {"hits": [
    {"objectID": "11", "title": "A big story", "url": "https://www.blog.example/post",
     "points": 420, "num_comments": 77, "created_at_i": 1794324320},
    {"objectID": "12", "title": "Ask HN: text post", "url": None, "points": 150,
     "num_comments": 5, "created_at_i": 1794324330},
    {"objectID": "", "title": "broken"},
    {"objectID": "13", "title": ""},
]}


def hn_fetch(url: str, params: dict) -> bytes:
    return json.dumps(HN).encode()


def extras_by_item(engine) -> dict[int, dict]:
    with Session(engine) as session:
        return {e.item_id: loads(e.data) for e in session.exec(select(ItemExtra)).all()}


def test_parse_hits_skips_malformed_and_uses_item_page_for_text_posts() -> None:
    stories = parse_hits(HN)
    assert [s["id"] for s in stories] == ["11", "12"]
    assert stories[1]["url"] == "https://news.ycombinator.com/item?id=12"
    assert stories[0]["points"] == 420


def test_fetch_stories_dedupes_across_both_searches_and_raises_when_both_fail() -> None:
    stories = fetch_stories(fetch=hn_fetch, now=1794400000)
    assert [s["id"] for s in stories] == ["11", "12"]  # same hits twice -> once each

    def down(url: str, params: dict) -> bytes:
        raise OSError("offline")

    with pytest.raises(RuntimeError):
        fetch_stories(fetch=down)


def test_collect_hackernews_stores_items_and_refreshes_points(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        assert collect_hackernews(engine, make_settings(), fetch=hn_fetch) == 2
        items = {i.external_id: i for i in all_items(engine, "hn")}
        assert items["11"].url == "https://www.blog.example/post"
        assert items["11"].origin == "blog.example"
        assert items["12"].origin == "Hacker News"
        extra = extras_by_item(engine)[items["11"].id]
        assert extra["points"] == 420
        assert extra["comments_url"] == "https://news.ycombinator.com/item?id=11"
        HN["hits"][0]["points"] = 900
        assert collect_hackernews(engine, make_settings(), fetch=hn_fetch) == 0
        assert extras_by_item(engine)[items["11"].id]["points"] == 900
    finally:
        HN["hits"][0]["points"] = 420
        engine.dispose()


HF = [
    {"paper": {"id": "2611.08379", "title": "Module-Aware\nOptimization", "summary": "An  idea.",
               "authors": [{"name": "Ada"}, {"name": "Bo"}], "upvotes": 12,
               "publishedAt": "2026-11-04T19:00:00.000Z"}, "title": "x"},
    {"paper": {"id": "", "title": "no id"}},
    {"paper": {"id": "2611.00001", "title": "Other", "upvotes": 3}},
]


def hf_fetch(url: str, params: dict) -> bytes:
    assert params["limit"] == 50
    return json.dumps(HF).encode()


def test_parse_papers_cleans_text_and_skips_entries_without_id() -> None:
    papers = parse_papers(HF)
    assert [p["arxiv_id"] for p in papers] == ["2611.08379", "2611.00001"]
    assert papers[0]["title"] == "Module-Aware Optimization"
    assert papers[0]["authors"] == ["Ada", "Bo"] and papers[0]["published"].year == 2026
    assert parse_papers({"not": "a list"}) == []


def test_collect_hf_papers_stores_extras_and_copies_votes_to_existing(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        store_items(engine, [
            CollectedItem(source="rss", external_id="r1", title="Same paper via feed",
                          url="https://arxiv.org/abs/2611.08379v2"),
            CollectedItem(source="rss", external_id="r2", title="Different id",
                          url="https://arxiv.org/abs/2611.083791"),
        ])
        assert collect_hf_papers(engine, make_settings(), fetch=hf_fetch) == 2
        papers = {i.external_id: i for i in all_items(engine, "hf_papers")}
        assert papers["2611.08379"].url == "https://arxiv.org/abs/2611.08379"
        extras = extras_by_item(engine)
        assert extras[papers["2611.08379"].id]["upvotes"] == 12
        assert extras[papers["2611.08379"].id]["authors"] == ["Ada", "Bo"]
        with Session(engine) as session:
            rss = {i.external_id: i.id for i in session.exec(
                select(Item).where(Item.source == "rss")).all()}
        assert extras[rss["r1"]]["upvotes"] == 12
        assert rss["r2"] not in extras  # a longer id must not match a shorter one
        assert collect_hf_papers(engine, make_settings(), fetch=hf_fetch) == 0
    finally:
        engine.dispose()


def test_collect_hf_papers_propagates_a_bad_response(tmp_path) -> None:
    engine = make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            collect_hf_papers(engine, make_settings(), fetch=lambda u, p: b"<html>nope")
    finally:
        engine.dispose()
