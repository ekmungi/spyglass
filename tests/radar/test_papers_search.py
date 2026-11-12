"""Tests for paper search: arXiv parsing, local matches, ranking and caching."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from spyglass_service.radar.models import RadarDoc
from spyglass_service.radar.papers import arxiv
from spyglass_service.radar.papers.search import find_papers, normalise_topic

from .test_brief_seed import NOW, add_item, make_engine, make_index

SETTINGS = SimpleNamespace(openrouter_api_key=None)


def entry(aid: str, title: str, published: str, summary: str = "An abstract.") -> str:
    """One Atom entry as arXiv returns it."""
    return f"""<entry><id>http://arxiv.org/abs/{aid}v2</id><title>{title}</title>
<summary>{summary}</summary><published>{published}T10:00:00Z</published>
<author><name>A. Author</name></author><author><name>B. Writer</name></author>
<link href="http://arxiv.org/abs/{aid}v2" rel="alternate" type="text/html"/>
<link title="pdf" href="http://arxiv.org/pdf/{aid}v2" rel="related" type="application/pdf"/></entry>"""


def feed(*entries: str) -> str:
    """An Atom feed holding the given entries."""
    return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>"


FEED = feed(
    entry("2606.00001", "Polyp detection with transformers", "2026-06-01"),
    entry("2401.00002", "Older colonoscopy benchmark", "2024-01-15"),
    entry("1505.00003", "Foundational segmentation network", "2015-05-18"),
)


def test_build_query_keeps_phrases_drops_stopwords_and_caps_terms() -> None:
    assert arxiv.build_query('AI in "polyp detection"') == 'all:"polyp detection" AND all:AI'
    assert arxiv.build_query("the of and") == ""
    q = arxiv.build_query("deep learning for early colorectal cancer screening")
    assert q.count("all:") == arxiv.MAX_TERMS and "all:colorectal" in q and "all:screening" in q


def test_generic_words_are_dropped_before_specific_ones() -> None:
    """"models" is longer than "polyp" but says nothing about the topic, so "polyp" must stay."""
    q = arxiv.build_query("foundation models for colonoscopy polyp detection")
    assert q == "all:foundation AND all:colonoscopy AND all:polyp AND all:detection"


def test_query_ladder_goes_from_precise_to_loose() -> None:
    rungs = arxiv.query_ladder("foundation models for colonoscopy polyp detection")
    assert rungs[0] == arxiv.build_query("foundation models for colonoscopy polyp detection")
    assert rungs[1].startswith("all:colonoscopy AND all:foundation AND (") and " OR " in rungs[1]
    assert " AND " not in rungs[2] and " OR " in rungs[2]
    assert arxiv.query_ladder("polyp detection") == ["all:polyp AND all:detection", "all:detection OR all:polyp"]
    assert len(arxiv.query_ladder("polyp")) == 1 and arxiv.query_ladder("the of") == []


def test_arxiv_id_from_and_parse_feed() -> None:
    assert arxiv.arxiv_id_from("https://arxiv.org/abs/2606.00001v3") == "2606.00001"
    assert arxiv.arxiv_id_from("https://arxiv.org/pdf/cs/0112017") == "cs/0112017"
    assert arxiv.arxiv_id_from("https://example.com/x") is None
    papers = arxiv.parse_feed(FEED)
    assert [p["arxiv_id"] for p in papers] == ["2606.00001", "2401.00002", "1505.00003"]
    first = papers[0]
    assert first["authors"] == ["A. Author", "B. Writer"] and first["published"] == "2026-06-01"
    assert first["pdf_url"].endswith("2606.00001v2") and first["url"] == "https://arxiv.org/abs/2606.00001"
    assert arxiv.parse_feed("not xml at all") == []


def test_search_arxiv_makes_one_call_when_the_precise_query_finds_enough() -> None:
    urls = []
    arxiv.search_arxiv("polyp detection", lambda u: urls.append(u) or FEED)
    assert len(urls) == 1
    assert urls[0].startswith("https://export.arxiv.org/api/query?search_query=")
    assert "sortBy=relevance" in urls[0] and "max_results=40" in urls[0]
    assert arxiv.search_arxiv("the of", lambda u: urls.append(u) or FEED) == [] and len(urls) == 1


def test_search_arxiv_loosens_the_query_when_the_precise_one_finds_nothing() -> None:
    urls = []

    def fetch(url: str) -> str:
        urls.append(url)
        return feed() if len(urls) == 1 else FEED

    papers = arxiv.search_arxiv("foundation models for colonoscopy polyp detection", fetch)
    assert len(urls) == 2 and len(papers) == 3
    assert "+AND+%28" in urls[1] or "AND+%28" in urls[1]


def test_search_arxiv_raises_when_the_first_request_fails_but_keeps_earlier_results() -> None:
    def down(url: str) -> str:
        raise OSError("no network")

    with pytest.raises(OSError):
        arxiv.search_arxiv("polyp detection", down)
    calls = []

    def second_fails(url: str) -> str:
        calls.append(url)
        if len(calls) == 1:
            return feed(entry("2606.00001", "Only one", "2026-06-01"))
        raise OSError("rate limited")

    assert [p["arxiv_id"] for p in arxiv.search_arxiv("polyp detection", second_fails)] == ["2606.00001"]


def test_lookup_arxiv_returns_papers_by_id_and_nothing_on_failure() -> None:
    urls = []
    found = arxiv.lookup_arxiv(["2606.00001"], lambda u: urls.append(u) or FEED)
    assert "id_list=2606.00001" in urls[0] and found["2606.00001"]["authors"] == ["A. Author", "B. Writer"]
    assert arxiv.lookup_arxiv([], lambda u: FEED) == {}

    def down(url: str) -> str:
        raise OSError("x")

    assert arxiv.lookup_arxiv(["2606.00001"], down) == {}


def test_picks_use_the_model_order_why_and_community_signal(tmp_path) -> None:
    engine = make_engine(tmp_path)
    add_item(engine, "Polyp detection with transformers", kind="paper", upvotes=17,
             url="https://arxiv.org/abs/2606.00001", arxiv_id="2606.00001")
    seen = {}

    def llm(messages, schema):
        seen["prompt"] = messages
        return {"picks": [{"index": 99, "why": "bad index"}, {"index": 1, "why": "Shows the older baseline."},
                          {"index": 0, "why": "Directly about your device area."}, {"index": 0, "why": "dup"}]}

    result = find_papers(engine, SETTINGS, None, "polyp detection", 2, llm=llm, fetch=lambda u: FEED, now=NOW)
    out = result["papers"]
    assert result["status"] == "ok" and result["notice"] is None
    assert [p["title"] for p in out] == ["Older colonoscopy benchmark", "Polyp detection with transformers"]
    assert out[1]["why"] == "Directly about your device area."
    assert out[1]["signal"] == "17 community upvotes" and out[1]["item_id"] is not None
    assert out[0]["signal"] is None and out[0]["item_id"] is None
    assert set(out[0]) == {"title", "authors", "published", "url", "pdf_url", "abstract", "why", "signal", "item_id"}
    assert out[0]["authors"] == ["A. Author", "B. Writer"]
    text = seen["prompt"][0]["content"]
    assert "builds with AI agents" in text  # the reader's profile statement is passed
    assert "24 months" in text and "fewer than 2" in text
    engine.dispose()


def test_without_a_model_newest_papers_come_first_and_the_answer_is_degraded(tmp_path) -> None:
    engine = make_engine(tmp_path)
    result = find_papers(engine, SETTINGS, None, "polyp detection", 3, fetch=lambda u: FEED, now=NOW)
    assert [p["published"] for p in result["papers"]] == ["2026-06-01", "2024-01-15", "2015-05-18"]
    assert all(p["why"] is None for p in result["papers"])
    assert result["status"] == "degraded"
    assert result["notice"] == ("The ranking model was unavailable; results are ordered by date and have "
                                "no relevance notes.")
    engine.dispose()


def test_failing_model_is_degraded_and_remembered_for_five_minutes_only(tmp_path) -> None:
    engine = make_engine(tmp_path)
    calls = []

    def boom(messages, schema):
        calls.append(1)
        raise RuntimeError("down")

    result = find_papers(engine, SETTINGS, None, "polyp detection", 2, llm=boom, fetch=lambda u: FEED, now=NOW)
    assert len(result["papers"]) == 2 and result["papers"][0]["why"] is None and result["status"] == "degraded"
    find_papers(engine, SETTINGS, None, "polyp detection", 2, llm=boom, fetch=lambda u: FEED,
                now=NOW + timedelta(minutes=4))
    assert len(calls) == 1
    find_papers(engine, SETTINGS, None, "polyp detection", 2, llm=boom, fetch=lambda u: FEED,
                now=NOW + timedelta(minutes=6))
    assert len(calls) == 2
    engine.dispose()


def test_complete_results_are_cached_for_twelve_hours_per_normalised_topic(tmp_path) -> None:
    engine = make_engine(tmp_path)
    fetches = []

    def fetch(url):
        fetches.append(url)
        return FEED

    llm = lambda m, s: {"picks": [{"index": 0, "why": "Relevant."}]}  # noqa: E731
    first = find_papers(engine, SETTINGS, None, "Polyp  Detection!", 1, llm=llm, fetch=fetch, now=NOW)
    again = find_papers(engine, SETTINGS, None, "polyp detection", 1, llm=llm, fetch=fetch,
                        now=NOW + timedelta(hours=11))
    assert again == first and len(fetches) == 1 and first["status"] == "ok"
    with Session(engine) as s:
        assert s.get(RadarDoc, "papers:polyp detection") is not None
    find_papers(engine, SETTINGS, None, "polyp detection", 1, llm=llm, fetch=fetch, now=NOW + timedelta(hours=13))
    assert len(fetches) == 2
    # Asking for more than was cached recomputes instead of returning too few.
    find_papers(engine, SETTINGS, None, "polyp detection", 3, llm=llm, fetch=fetch, now=NOW + timedelta(hours=14))
    assert len(fetches) == 3
    engine.dispose()


def _library(engine) -> dict[str, int]:
    """Four stored items: a DOI paper, an arXiv paper, a paper-kind news story and a far DOI paper."""
    return {
        "doi": add_item(engine, "Colonoscopy polyp study", kind="paper", url="https://doi.org/10.1000/polyp1"),
        "arxiv": add_item(engine, "Polyp detection advances", kind="paper", url="https://arxiv.org/abs/2606.00009",
                          arxiv_id="2606.00009"),
        "news": add_item(engine, "Colonoscopy screening news", kind="paper", url="https://example.org/paper/1"),
        "far": add_item(engine, "Unrelated physics paper", kind="paper", url="https://doi.org/10.1000/physics"),
    }


def test_arxiv_failure_gives_only_close_real_papers_from_the_library_and_a_notice(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = _library(engine)
    index = make_index({ids["doi"]: [1, 1, 1, 0], ids["arxiv"]: [1, 1, 0.6, 0], ids["news"]: [1, 1, 1, 0.1],
                        ids["far"]: [1, -1, 0, 0]})

    def broken(url):
        raise OSError("no network")

    result = find_papers(engine, SETTINGS, index, "polyp detection", 5, fetch=broken, now=NOW)
    assert {p["title"] for p in result["papers"]} == {"Colonoscopy polyp study", "Polyp detection advances"}
    assert result["status"] == "degraded"
    assert result["notice"].startswith(
        "The paper search service did not answer; showing matches from your own library only.")
    engine.dispose()


def test_nothing_is_added_to_fill_the_list_when_nothing_qualifies(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = _library(engine)
    index = make_index({ids["doi"]: [1, -1, 0, 0], ids["arxiv"]: [1, -1, 0.2, 0], ids["news"]: [1, 1, 1, 0],
                        ids["far"]: [1, -1, 0, 0]})
    result = find_papers(engine, SETTINGS, index, "polyp detection", 5, fetch=lambda u: feed(), now=NOW)
    assert result == {"papers": [], "status": "empty", "notice": "No papers matched this topic."}
    engine.dispose()


def test_empty_answer_when_arxiv_is_down_and_the_library_has_nothing_close(tmp_path) -> None:
    engine = make_engine(tmp_path)

    def broken(url):
        raise OSError("no network")

    result = find_papers(engine, SETTINGS, None, "polyp", 5, fetch=broken, now=NOW)
    assert result["papers"] == [] and result["status"] == "empty"
    assert "did not answer" in result["notice"]
    engine.dispose()


def test_a_model_that_picks_nothing_gives_an_empty_answer(tmp_path) -> None:
    engine = make_engine(tmp_path)
    result = find_papers(engine, SETTINGS, None, "polyp detection", 3, llm=lambda m, s: {"picks": []},
                         fetch=lambda u: FEED, now=NOW)
    assert result["papers"] == [] and result["status"] == "empty"
    engine.dispose()


def test_authors_of_a_library_paper_are_filled_from_arxiv(tmp_path) -> None:
    engine = make_engine(tmp_path)
    ids = _library(engine)
    index = make_index({ids["doi"]: [1, -1, 0, 0], ids["arxiv"]: [1, 1, 1, 0], ids["news"]: [1, -1, 0, 0],
                        ids["far"]: [1, -1, 0, 0]})
    lookup = feed(entry("2606.00009", "Polyp detection advances", "2026-05-05"))
    urls = []

    def fetch(url):
        urls.append(url)
        return lookup if "id_list" in url else feed()

    llm = lambda m, s: {"picks": [{"index": 0, "why": "Close to your topic."}]}  # noqa: E731
    result = find_papers(engine, SETTINGS, index, "polyp detection", 3, llm=llm, fetch=fetch, now=NOW)
    paper = result["papers"][0]
    assert paper["authors"] == ["A. Author", "B. Writer"] and paper["item_id"] == ids["arxiv"]
    assert any("id_list=2606.00009" in u for u in urls)
    engine.dispose()


def test_empty_everything_gives_empty_status_and_normalise_topic_works(tmp_path) -> None:
    engine = make_engine(tmp_path)
    result = find_papers(engine, SETTINGS, None, "polyp", 5, fetch=lambda u: feed(), now=NOW)
    assert result["papers"] == [] and result["status"] == "empty"
    assert normalise_topic("  A, b!  ") == "a b"
    engine.dispose()


def test_an_answer_stored_before_statuses_existed_is_not_served(tmp_path) -> None:
    from spyglass_service.radar.models import dumps

    engine = make_engine(tmp_path)
    with Session(engine) as s:
        s.add(RadarDoc(key="papers:polyp detection", body=dumps({"limit": 8, "papers": [{"title": "Old padding"}]}),
                       updated_at=NOW))
        s.commit()
    result = find_papers(engine, SETTINGS, None, "polyp detection", 3, fetch=lambda u: FEED, now=NOW)
    assert "Old padding" not in {p["title"] for p in result["papers"]}
    engine.dispose()
