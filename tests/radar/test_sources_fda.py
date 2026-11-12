"""FDA device decisions as watch items: matching, item shape, dedupe, the request cap, failures.

The fixtures in `fda_fixtures/` are small JSON files written by hand in the documented openFDA
response shape (an object with `meta` and `results`). No test touches the network: the collector's
fetch function is replaced by a fake that answers from those files and records what it was asked.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, select

from spyglass_service.models import Item, RunLog
from spyglass_service.radar import netguard
from spyglass_service.radar.models import ItemEntity, WatchEntity
from spyglass_service.radar.sources import COLLECTORS, collect_all, fda, fda_records
from spyglass_service.radar.sources._common import NotConfigured
from spyglass_service.radar.watch.registry import create_entity

from .test_sources_support import make_engine

FIXTURES = Path(__file__).parent / "fda_fixtures"
TODAY = date(2026, 11, 12)
ENDPOINT_FILES = {"510k.json": "510k.json", "pma.json": "pma.json", "recall.json": "recall.json"}


def load(name: str) -> dict:
    """A fixture's parsed JSON."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeFetch:
    """A fetch function answering from the fixtures and recording every request."""

    def __init__(self, overrides: dict | None = None) -> None:
        """`overrides` maps an endpoint file name to a (status, body) pair or an exception."""
        self.calls: list[tuple[str, dict]] = []
        self.overrides = overrides or {}

    def __call__(self, url: str, params: dict) -> tuple[int, bytes]:
        """Answer one request."""
        self.calls.append((url, params))
        name = url.rsplit("/", 1)[-1]
        answer = self.overrides.get(name)
        if isinstance(answer, Exception):
            raise answer
        if answer is not None:
            return answer
        return 200, json.dumps(load(name)).encode()


def settings(**extra):
    """A settings stand-in with the FDA fields."""
    base = {"radar_fda_enabled": True, "radar_fda_product_codes": "", "radar_fda_keywords": ""}
    return SimpleNamespace(**{**base, **extra})


def run(targets, **kw):
    """`fda.search` with a fake fetch, no real sleeping and a fixed date."""
    fetch = kw.pop("fetch", None) or FakeFetch()
    result = fda.search(targets, fetch=fetch, sleep=kw.pop("sleep", lambda _s: None),
                        today=TODAY, **kw)
    return result, fetch


# ---- matching ----------------------------------------------------------------------------------


@pytest.mark.parametrize("name,candidate", [
    ("Intuitive Surgical", "Intuitive Surgical, Inc."),
    ("Intuitive Surgical, Inc.", "INTUITIVE SURGICAL INC"),
    ("Intuitive Surgical", "Intuitive Surgical Operations, Inc."),
    ("Olympus", "Olympus Medical Systems Corp."),
    ("Olympus Corporation", "Olympus Surgical Technologies America"),
    ("Siemens Healthineers", "Siemens Healthineers AG"),
])
def test_names_match_exactly_or_by_starting_words(name: str, candidate: str) -> None:
    """Exact (ignoring case, punctuation and legal endings) and 'starts with whole words' match."""
    assert fda_records.name_matches([name], candidate)


@pytest.mark.parametrize("name,candidate", [
    ("Intuitive Surgical", "Intuitive Machines, Inc."),
    ("Olympus", "Not Olympus Inc"),
    ("Olympus", "Olympusx Ltd"),
    ("Surgical", "Intuitive Surgical, Inc."),
    ("GE", "GE Healthcare"),
    ("Intuitive Surgical", ""),
    ("", "Intuitive Surgical, Inc."),
])
def test_names_never_match_loosely(name: str, candidate: str) -> None:
    """Contains-matches, partial words, very short names and empty names never match."""
    assert not fda_records.name_matches([name], candidate)


def test_an_alias_matches_too() -> None:
    """Any of the entity's names (its aliases included) may match."""
    assert fda_records.name_matches(["Philips", "Koninklijke Philips"], "Koninklijke Philips N.V.")


# ---- item shape --------------------------------------------------------------------------------


def test_a_clearance_becomes_one_regulator_item() -> None:
    """Headline, link, date, source label, summary fields and the record-number identity."""
    record = load("510k.json")["results"][0]
    item = fda_records.item_510k(record)
    assert item.title == ("FDA clears da Vinci Xi Surgical System (IS4000) and 1 more from "
                          "Intuitive Surgical, Inc. (510(k) K263592)")
    assert item.url == ("https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm"
                        "?ID=K263592")
    assert item.published_at == datetime(2026, 10, 30, tzinfo=UTC)
    assert item.external_id == "fda:510k:K263592" and item.source == "watch"
    assert item.origin == "FDA" and "regulator" in item.source_tags
    assert "da Vinci X Surgical System (IS4200)" in item.summary  # the summary lists every model
    for part in ("Substantially Equivalent", "NAY", "System, Surgical, Computer Controlled "
                 "Instrument", "Gastroenterology, Urology", "2026-10-30", "Special"):
        assert part in item.summary
    assert "\n" not in item.summary


def test_a_de_novo_grant_is_labelled_as_one() -> None:
    """De Novo decisions arrive in the 510(k) data under DEN numbers with decision code DENG."""
    item = fda_records.item_510k(load("510k.json")["results"][1])
    assert item.title.startswith("FDA grants De Novo for Virtuoso Endoscopy System from Intuitive")
    assert "DEN250054" in item.title and item.external_id == "fda:denovo:DEN250054"
    assert "denovo" in item.url.lower()


def test_decisions_that_are_not_clearances_are_skipped() -> None:
    """A not-substantially-equivalent decision, or a record with no date, is not an item."""
    records = load("510k.json")["results"]
    assert fda_records.item_510k(records[2]) is None
    assert fda_records.item_510k({**records[0], "decision_date": ""}) is None
    assert fda_records.item_510k({**records[0], "k_number": ""}) is None


def test_text_from_the_api_is_cleaned_like_other_collected_text() -> None:
    """Control characters and invisible marks are removed; the text stays one line."""
    item = fda_records.item_510k(load("510k.json")["results"][4])
    assert "\n" not in item.title and "​" not in item.title
    assert "EVIS X1 Colonoscope" in item.title


def test_pma_approvals_and_important_supplements_are_items() -> None:
    """An original approval and a panel-track supplement are kept; a 30-day notice is not."""
    records = load("pma.json")["results"]
    original, notice, panel = (fda_records.item_pma(r) for r in records)
    assert original.title == "FDA approves EXAMPLE VALVE from Medtronic, Inc. (PMA P040024)"
    assert original.external_id == "fda:pma:P040024"
    assert original.url.endswith("pma.cfm?id=P040024")
    assert notice is None
    assert panel.external_id == "fda:pma:P040024/S020" and "supplement" in panel.title
    assert panel.url.endswith("pma.cfm?id=P040024S020")


def test_a_recall_event_with_several_products_is_one_item() -> None:
    """Records of one recall event merge; the dedupe key is the event number."""
    items = fda_records.items_recall(load("recall.json")["results"])
    assert [i.external_id for i in items] == ["fda:recall:27549", "fda:recall:27600"]
    first = items[0]
    assert "recall" in first.title.lower() and "Intuitive Surgical, Inc." in first.title
    assert "Staple line" in first.summary and "2 products" in first.summary
    assert first.url.endswith("res.cfm?ID=30043")


def test_a_recall_without_a_record_id_links_to_the_recall_search_not_to_a_wrong_record() -> None:
    """The record id in the address is not the event number, so the event number is never used."""
    records = [{**r, "cfres_id": ""} for r in load("recall.json")["results"]]
    for item in fda_records.items_recall(records):
        assert item.url == "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm"


def test_a_de_novo_grant_links_to_the_de_novo_record() -> None:
    """The De Novo record address carries the DEN number (the form the FDA's own pages use)."""
    grant = next(fda_records.item_510k(r) for r in load("510k.json")["results"]
                 if r.get("decision_code") == "DENG")
    assert grant.url == ("https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/denovo.cfm"
                         "?id=DEN250054")


# ---- the search --------------------------------------------------------------------------------


def test_a_watched_company_gets_its_decisions_and_nothing_else() -> None:
    """Matching decisions of all three kinds, tagged with the entity, without unrelated firms."""
    result, fetch = run([fda.Target(7, ("Intuitive Surgical",))])
    ids = sorted(i.external_id for i in result.items)
    assert ids == ["fda:510k:K263592", "fda:denovo:DEN250054", "fda:recall:27549",
                   "fda:recall:27600"]
    assert all("watch:7" in i.source_tags for i in result.items)
    assert len(fetch.calls) == 3 and result.requests == 3


def test_the_query_is_an_exact_phrase_inside_the_last_thirty_days() -> None:
    """Each request names the firm as a quoted phrase and a 30-day decision window."""
    _result, fetch = run([fda.Target(1, ("Intuitive Surgical",))])
    by_endpoint = {url.rsplit("/", 1)[-1]: params for url, params in fetch.calls}
    assert set(by_endpoint) == {"510k.json", "pma.json", "recall.json"}
    assert 'applicant:"Intuitive Surgical"' in by_endpoint["510k.json"]["search"]
    assert 'recalling_firm:"Intuitive Surgical"' in by_endpoint["recall.json"]["search"]
    assert "[2026-10-13 TO 2026-11-12]" in by_endpoint["510k.json"]["search"]
    assert all(url.startswith("https://api.fda.gov/device/") for url, _ in fetch.calls)
    assert all(params["limit"] == 100 for params in by_endpoint.values())


def test_a_record_found_for_two_entities_is_one_item_with_both_tags() -> None:
    """Dedupe by record number across entities, keeping both links."""
    result, _ = run([fda.Target(1, ("Intuitive Surgical",)), fda.Target(2, ("Intuitive",))])
    k = [i for i in result.items if i.external_id == "fda:510k:K263592"]
    assert len(k) == 1 and {"watch:1", "watch:2"} <= set(k[0].source_tags)


def test_product_codes_and_keywords_are_searched_without_an_entity() -> None:
    """The owner's lists add one query per endpoint; their items carry no watch tag."""
    result, fetch = run([], codes=("NAY", "FDF"), keywords=("colonoscope",))
    searches = [params["search"] for _url, params in fetch.calls]
    assert any('product_code:"NAY"' in s and 'product_code:"FDF"' in s for s in searches)
    assert any('device_name:"colonoscope"' in s for s in searches)
    assert result.items and all(not any(t.startswith("watch:") for t in i.source_tags)
                                for i in result.items)


def test_the_request_cap_is_hard_and_the_next_run_resumes() -> None:
    """With a cap of 6 requests, two entities are covered; the result says where it stopped."""
    targets = [fda.Target(n, (f"Maker {n}",)) for n in range(1, 6)]
    result, fetch = run(targets, max_requests=6)
    assert len(fetch.calls) == 6 and result.requests == 6
    assert result.covered == 2 and result.stopped == "request limit"


def test_requests_are_spaced_at_least_a_second_apart() -> None:
    """One pause between requests, none before the first."""
    pauses: list[float] = []
    _result, fetch = run([fda.Target(1, ("Intuitive Surgical",))], sleep=pauses.append)
    assert len(pauses) == len(fetch.calls) - 1 and all(p >= 1.0 for p in pauses)


def test_one_failing_endpoint_does_not_stop_the_others() -> None:
    """A network error on the PMA lookup still returns the 510(k) and recall items."""
    fetch = FakeFetch({"pma.json": httpx.ConnectError("boom")})
    result, _ = run([fda.Target(1, ("Intuitive Surgical",))], fetch=fetch)
    assert result.failures == 1 and any(i.external_id.startswith("fda:510k") for i in result.items)


def test_no_match_is_not_a_failure() -> None:
    """openFDA answers 404 'No matches found!' for an empty result; that is an empty list."""
    body = b'{"error": {"code": "NOT_FOUND", "message": "No matches found!"}}'
    fetch = FakeFetch({name: (404, body) for name in ENDPOINT_FILES})
    result, _ = run([fda.Target(1, ("Intuitive Surgical",))], fetch=fetch)
    assert result.items == [] and result.failures == 0


def test_a_rate_limit_stops_the_run_but_keeps_what_was_found() -> None:
    """HTTP 429 ends the run early (more requests would only be refused)."""
    fetch = FakeFetch({"pma.json": (429, b"{}")})
    result, _ = run([fda.Target(1, ("Intuitive Surgical",)), fda.Target(2, ("Olympus",))],
                    fetch=fetch)
    assert result.stopped == "rate limit" and result.items


def test_every_request_failing_raises() -> None:
    """When nothing at all could be read the source reports an error, not an empty success."""
    fetch = FakeFetch({name: (500, b"oops") for name in ENDPOINT_FILES})
    with pytest.raises(RuntimeError, match="openFDA"):
        run([fda.Target(1, ("Intuitive Surgical",))], fetch=fetch)


def test_bad_product_codes_and_keywords_are_ignored() -> None:
    """Only plain codes and keywords become search text; anything else is dropped."""
    assert fda.parse_list("NAY, fdf ; bad code!!, x", fda.CODE_PATTERN) == ("NAY", "FDF")
    assert fda.parse_list('colonoscope, "quote", a\nb', fda.KEYWORD_PATTERN) == ("colonoscope", "a b")


# ---- the real fetch goes through the guard -----------------------------------------------------


def _mock_page_client(handler, seen: list):
    """A page_client replacement: the guarded client over a mock transport."""
    def factory(**kwargs):
        seen.append(kwargs)
        return netguard.guard_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return factory


def test_the_default_fetch_uses_the_guarded_client_pinned_to_the_api_host(monkeypatch) -> None:
    """The request goes through netguard.page_client without redirects, to api.fda.gov only."""
    requests: list[httpx.Request] = []
    seen: list = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(netguard, "page_client", _mock_page_client(handler, seen))
    status, _body = fda.default_fetch("https://api.fda.gov/device/510k.json", {"search": "x"})
    assert status == 200 and requests[0].url.host == "api.fda.gov"
    assert seen[0]["follow_redirects"] is False
    assert "authorization" not in requests[0].headers and "cookie" not in requests[0].headers


@pytest.mark.parametrize("url", ["https://example.org/device/510k.json",
                                 "http://api.fda.gov/device/510k.json",
                                 "https://api.fda.gov.evil.example/x"])
def test_the_default_fetch_refuses_any_other_host(url: str) -> None:
    """Only https on api.fda.gov is allowed, whatever the caller passes."""
    with pytest.raises(ValueError, match="api.fda.gov"):
        fda.default_fetch(url, {})


def test_the_default_fetch_is_refused_when_the_host_resolves_privately(monkeypatch) -> None:
    """If api.fda.gov ever answered with a private address the guard refuses the request."""
    monkeypatch.setattr(netguard, "resolve", lambda _h: ["10.0.0.9"])
    netguard.clear_lookup_cache()
    with pytest.raises(netguard.BlockedAddress):
        fda.default_fetch("https://api.fda.gov/device/510k.json", {})


# ---- storing, settings and the daily schedule --------------------------------------------------


def _engine_with_entities(tmp_path):
    """A database with one active company, one muted company and one regulator."""
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        create_entity(session, "Intuitive Surgical", kind="company", category="Surgical robotics")
        create_entity(session, "Muted Maker", kind="company", status="muted")
        create_entity(session, "US FDA", kind="regulator")
    return engine


def test_collect_fda_stores_items_and_links_them_to_the_entity(tmp_path) -> None:
    """New items are stored under the watch source and shown under the organisation."""
    engine = _engine_with_entities(tmp_path)
    try:
        fetch = FakeFetch()
        new, detail = fda.collect_fda(engine, settings(), fetch=fetch, sleep=lambda _s: None,
                                      today=TODAY)
        assert new == 4 and detail.startswith("4 new")
        assert len(fetch.calls) == 3  # one company, three endpoints; muted and regulator skipped
        with Session(engine) as session:
            items = session.exec(select(Item).where(Item.source == "watch")).all()
            assert len(items) == 4 and all(i.origin == "FDA" for i in items)
        from spyglass_service.radar.watch.sweep import link_watch_items

        assert link_watch_items(engine) == 4
        with Session(engine) as session:
            links = session.exec(select(ItemEntity)).all()
            entity = session.exec(select(WatchEntity).where(
                WatchEntity.name == "Intuitive Surgical")).one()
        assert len(links) == 4 and {link.entity_id for link in links} == {entity.id}
        again, _ = fda.collect_fda(engine, settings(), fetch=FakeFetch(),
                                   sleep=lambda _s: None, today=TODAY)
        assert again == 0  # the same records are not stored twice
    finally:
        engine.dispose()


def test_collect_fda_resumes_after_the_cap(tmp_path) -> None:
    """Entities left out by the cap are the first ones the next run covers."""
    engine = make_engine(tmp_path)
    try:
        with Session(engine) as session:
            for n in range(1, 5):
                create_entity(session, f"Maker {n}", kind="company")
        first = FakeFetch()
        fda.collect_fda(engine, settings(), fetch=first, sleep=lambda _s: None, today=TODAY,
                        max_requests=6)
        second = FakeFetch()
        fda.collect_fda(engine, settings(), fetch=second, sleep=lambda _s: None, today=TODAY,
                        max_requests=6)
        asked = lambda f: {p["search"].split('"')[1] for _u, p in f.calls}  # noqa: E731
        assert asked(first) == {"Maker 1", "Maker 2"} and asked(second) == {"Maker 3", "Maker 4"}
    finally:
        engine.dispose()


def test_switched_off_is_not_an_error(tmp_path) -> None:
    """With the setting off the collector says it is not configured and sends nothing."""
    engine = _engine_with_entities(tmp_path)
    try:
        fetch = FakeFetch()
        with pytest.raises(NotConfigured):
            fda.collect_fda(engine, settings(radar_fda_enabled=False), fetch=fetch)
        assert fetch.calls == []
    finally:
        engine.dispose()


def test_nothing_to_look_for_makes_no_requests(tmp_path) -> None:
    """No active company and empty lists: no request, no failure."""
    engine = make_engine(tmp_path)
    try:
        fetch = FakeFetch()
        assert fda.collect_fda(engine, settings(), fetch=fetch)[0] == 0
        assert fetch.calls == []
    finally:
        engine.dispose()


def test_fda_is_a_daily_collector_with_its_own_status_row(tmp_path) -> None:
    """It runs once a day like the watch sweep, is logged, and a failure leaves the cycle intact."""
    assert "fda" in COLLECTORS
    engine = make_engine(tmp_path)
    try:
        calls: list[str] = []

        def table(boom: bool):
            def runner(key):
                def run_it(_e, _s):
                    calls.append(key)
                    if key == "fda" and boom:
                        raise RuntimeError("openFDA unreachable")
                    return 1, "1 new"
                return run_it
            return {key: runner(key) for key in COLLECTORS}

        counts = collect_all(engine, settings(), runners=table(True))
        assert counts["fda"] == 0 and counts["news"] == 1
        with Session(engine) as session:
            last = session.exec(select(RunLog).where(RunLog.source == "radar:fda")
                                .order_by(RunLog.id.desc())).first()
        assert last.status == "error" and "openFDA" in last.detail
        collect_all(engine, settings(), runners=table(False))   # retried: a failure is not a day's run
        collect_all(engine, settings(), runners=table(False))   # now done for today: skipped
        assert calls.count("fda") == 2
        collect_all(engine, settings(), runners=table(False), force_watch=True)
        assert calls.count("fda") == 3
    finally:
        engine.dispose()


def test_the_sources_screen_labels_the_fda_collector() -> None:
    """The status row has a readable label."""
    from spyglass_service.radar.api.sources import COLLECTOR_LABELS

    assert COLLECTOR_LABELS["fda"] == "FDA device decisions"


