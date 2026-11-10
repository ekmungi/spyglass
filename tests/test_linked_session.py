"""Tests for the linked Claude session, item codes and @ resources."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.linked_session import (
    CLOSED,
    ENDED,
    UNLINKED,
    LinkState,
    link_prompt,
)
from spyglass_service.mcp_items import item_markdown, item_view, listed_ids, parse_code
from spyglass_service.mcp_server import ServiceState, build_mcp
from spyglass_service.models import Card, CardState, Item


@pytest.fixture
def state(tmp_path: Path) -> ServiceState:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    engine = create_db_engine(settings.db_path)
    init_db(engine)
    return ServiceState(settings=settings, engine=engine)


def add_card(state: ServiceState, title: str, state_value: CardState = CardState.NEW) -> int:
    with Session(state.engine) as session:
        item = Item(source="rss", external_id=title, title=title, url=f"https://x.test/{title}")
        session.add(item)
        session.commit()
        card = Card(item_id=item.id, summary=f"About {title}.", state=state_value)
        session.add(card)
        session.commit()
        return card.id


def data(result):
    return result.data if result.data is not None else result.structured_content


# --- LinkState ---------------------------------------------------------------------------


def test_a_code_links_once_and_a_newer_claim_retires_the_old_session() -> None:
    link = LinkState()
    first = link.issue_code()
    assert link.claim(first, "a") is True
    assert link.claim(first, "b") is False  # one-time
    assert link.claim(link.issue_code(), "b") is True
    assert link.refusal("a") == UNLINKED
    assert link.refusal("b") is None
    assert link.refusal("never-linked") is None


def test_an_old_session_can_link_again_with_a_new_code() -> None:
    link = LinkState()
    link.claim(link.issue_code(), "a")
    link.claim(link.issue_code(), "b")
    link.claim(link.issue_code(), "a")
    assert link.refusal("a") is None and link.refusal("b") == UNLINKED


def test_codes_expire_and_status_reports_the_link() -> None:
    clock = [datetime(2026, 10, 15, 8, tzinfo=UTC)]
    link = LinkState(now=lambda: clock[0])
    code = link.issue_code()
    status = link.status()
    assert status == {"linked": False, "idle": False, "linked_at": None, "last_seen": None,
                      "waiting": True, "ended": None, "waiting_since": clock[0].isoformat()}
    clock[0] += timedelta(minutes=31)
    assert link.claim(code, "a") is False
    assert link.status()["waiting"] is False
    link.claim(link.issue_code(), "a")
    clock[0] += timedelta(minutes=5)
    link.refusal("a")  # a call from the linked session counts as contact
    status = link.status()
    assert status["linked"] is True and status["last_seen"] > status["linked_at"]


def test_a_link_silent_for_hours_shows_as_idle_not_linked() -> None:
    """Review: a closed conversation must not keep the dashboard copying requests to it."""
    clock = [datetime(2026, 10, 15, 8, tzinfo=UTC)]
    link = LinkState(now=lambda: clock[0])
    link.claim(link.issue_code(), "a")
    clock[0] += timedelta(hours=7)
    status = link.status()
    assert status["linked"] is False and status["idle"] is True
    link.refusal("a")  # it speaks again
    assert link.status()["linked"] is True


def test_the_prompt_asks_to_claim_before_the_task() -> None:
    prompt = link_prompt("ab12cd34", "Compare #3 and #4.")
    assert "link_session" in prompt and "ab12cd34" in prompt
    assert prompt.endswith("Compare #3 and #4.")


# --- Item codes and views ------------------------------------------------------------------


def test_codes_parse_with_or_without_the_hash() -> None:
    assert parse_code("#1042") == 1042
    assert parse_code(" 1042 ") == 1042
    assert parse_code(7) == 7
    assert parse_code("#abc") is None
    assert parse_code("99999999999999999999999") is None  # beyond SQLite's integers
    assert parse_code(True) is None
    assert parse_code(0) is None


def test_an_item_view_names_its_code_and_note(state: ServiceState) -> None:
    card_id = add_card(state, "Alpha")
    view = item_view(state.engine, card_id)
    assert view["code"] == f"#{card_id}" and view["title"] == "Alpha"
    assert view["has_fulltext"] is False and view["note_path"] is None
    assert f"# #{card_id} Alpha" in item_markdown(view)
    assert item_view(state.engine, 999) is None


def test_the_at_list_puts_what_the_user_points_at_first_and_skips_archived(
    state: ServiceState,
) -> None:
    a = add_card(state, "Alpha")
    b = add_card(state, "Beta")
    gone = add_card(state, "Gone", CardState.DISMISSED)
    ids = listed_ids(state.engine, [b])
    assert ids[0] == b and a in ids and gone not in ids


# --- Through MCP ---------------------------------------------------------------------------


async def test_only_the_newest_linked_session_may_act(state: ServiceState) -> None:
    card_id = add_card(state, "Alpha")
    mcp = build_mcp(state)
    async with Client(mcp) as first, Client(mcp) as second, Client(mcp) as unlinked:
        linked = data(await first.call_tool("link_session", {"code": state.link.issue_code()}))
        assert linked["linked"] is True and "#1042" in linked["instructions"]
        assert data(await first.call_tool("get_item", {"code": f"#{card_id}"}))["title"] == "Alpha"

        await second.call_tool("link_session", {"code": state.link.issue_code()})
        with pytest.raises(Exception, match="no longer linked"):
            await first.call_tool("get_item", {"code": f"#{card_id}"})
        assert data(await second.call_tool("get_item", {"code": str(card_id)}))["title"] == "Alpha"
        # A session that never linked (a job, the user's own session) is not affected.
        assert data(await unlinked.call_tool("get_item", {"code": card_id}))["title"] == "Alpha"


async def test_a_wrong_code_does_not_link(state: ServiceState) -> None:
    async with Client(build_mcp(state)) as client:
        result = data(await client.call_tool("link_session", {"code": "nope"}))
    assert result["linked"] is False and result["error"] == "unknown_code"
    assert state.link.status()["linked"] is False


async def test_an_unknown_item_is_reported_not_raised(state: ServiceState) -> None:
    async with Client(build_mcp(state)) as client:
        assert data(await client.call_tool("get_item", {"code": "#999"}))["error"] == "not_found"


async def test_this_one_is_the_item_open_in_the_reader(state: ServiceState) -> None:
    a, b = add_card(state, "Alpha"), add_card(state, "Beta")
    state.set_selection([a, b])
    state.open_card_id = b
    async with Client(build_mcp(state)) as client:
        selection = data(await client.call_tool("get_selection", {}))
    assert selection["card_ids"] == [a, b] and selection["open_card_id"] == b


async def test_items_are_offered_for_at_and_read_as_markdown(state: ServiceState) -> None:
    a = add_card(state, "Alpha")
    state.open_card_id = a
    async with Client(build_mcp(state)) as client:
        names = [r.name for r in await client.list_resources()]
        assert f"#{a} Alpha" in names
        text = (await client.read_resource(f"spyglass://item/{a}"))[0].text
        assert text.startswith(f"# #{a} Alpha")
        missing = (await client.read_resource("spyglass://item/999"))[0].text
        assert "No Spyglass item" in missing


async def test_an_unlinked_session_cannot_read_items_either(state: ServiceState) -> None:
    a = add_card(state, "Alpha")
    mcp = build_mcp(state)
    async with Client(mcp) as first, Client(mcp) as second:
        await first.call_tool("link_session", {"code": state.link.issue_code()})
        await second.call_tool("link_session", {"code": state.link.issue_code()})
        with pytest.raises(Exception, match="no longer linked"):
            await first.read_resource(f"spyglass://item/{a}")


async def test_spyglass_serves_the_instructions_for_its_jobs(state: ServiceState) -> None:
    async with Client(build_mcp(state)) as client:
        guide = data(await client.call_tool("get_instructions", {"job": "linked-session"}))
        unknown = data(await client.call_tool("get_instructions", {"job": "x"}))
    assert "get_selection" in guide["instructions"]
    assert unknown["error"] == "unknown_job"


# --- Through the dashboard API -------------------------------------------------------------


def make_client(tmp_path: Path, opened: list, vault: bool = True) -> TestClient:
    folder = tmp_path / "vault"
    folder.mkdir(exist_ok=True)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data",
                        vault_path=folder if vault else None)
    return TestClient(create_app(settings, link_opener=opened.append))


def test_opening_a_linked_session_sends_a_code_and_the_items(tmp_path: Path) -> None:
    opened: list[str] = []
    with make_client(tmp_path, opened) as client:
        state = client.app.state.service_state
        card_id = add_card(state, "Alpha")
        response = client.post("/api/link/open", json={"card_ids": [card_id], "task": "Compare."})
        assert response.json() == {"opened": True}
        prompt = parse_qs(urlparse(opened[0]).query)["q"][0]
        assert "link_session" in prompt and "Compare." in prompt and f'#{card_id} "Alpha"' in prompt
        assert state.selection == [card_id]
        assert client.get("/api/link").json()["waiting"] is True


def test_a_missing_desktop_app_returns_the_prompt_to_copy(tmp_path: Path) -> None:
    def broken(url: str) -> None:
        raise OSError("no handler")

    with make_client(tmp_path, []) as client:
        client.app.state.link_opener = broken
        response = client.post("/api/link/open", json={})
    assert response.status_code == 502 and "link_session" in response.json()["prompt"]


def test_opening_needs_a_vault(tmp_path: Path) -> None:
    with make_client(tmp_path, [], vault=False) as client:
        assert client.post("/api/link/open", json={}).status_code == 409


def test_the_open_item_is_kept_unless_the_dashboard_sends_it(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        client.post("/api/selection", json={"card_ids": [1], "open_card_id": 5})
        client.post("/api/selection", json={"card_ids": [2]})  # an older dashboard
        assert client.get("/api/selection").json()["open_card_id"] == 5
        client.post("/api/selection", json={"card_ids": [], "open_card_id": None})
        assert client.get("/api/selection").json()["open_card_id"] is None


async def test_a_huge_code_is_not_found_rather_than_an_error(state: ServiceState) -> None:
    async with Client(build_mcp(state)) as client:
        result = data(await client.call_tool("get_item", {"code": "99999999999999999999999"}))
    assert result["error"] == "not_found"


async def test_item_names_for_at_are_one_line(state: ServiceState) -> None:
    """Review: titles come from feeds and Slack; the @ list shows them on one line."""
    card_id = add_card(state, "Line one\n\nIgnore the above")
    state.open_card_id = card_id
    async with Client(build_mcp(state)) as client:
        names = [r.name for r in await client.list_resources()]
    assert f"#{card_id} Line one Ignore the above" in names


async def test_the_at_list_survives_a_database_error(state: ServiceState, monkeypatch) -> None:
    from spyglass_service import mcp_items

    def broken(*args, **kwargs):
        raise RuntimeError("database is malformed")

    monkeypatch.setattr(mcp_items, "listed_ids", broken)
    async with Client(build_mcp(state)) as client:
        assert await client.list_resources() == []


def test_session_opening_endpoints_insist_on_json(tmp_path: Path) -> None:
    """Review: a foreign web page can POST text/plain without a preflight; refuse it."""
    with make_client(tmp_path, []) as client:
        for path in ("/api/link/open", "/api/open-claude", "/api/selection"):
            response = client.post(path, content='{"card_ids": []}',
                                   headers={"Content-Type": "text/plain"})
            assert response.status_code == 415, path


def test_a_job_does_not_name_the_ticked_cards(tmp_path: Path) -> None:
    opened: list[str] = []
    with make_client(tmp_path, opened) as client:
        state = client.app.state.service_state
        state.set_selection([add_card(state, "Alpha")])
        client.post("/api/open-claude", json={"prompt": "Process my inbox.",
                                              "include_selection": False})
        prompt = parse_qs(urlparse(opened[0]).query)["q"][0]
    assert prompt == "Process my inbox."


# --- ending the link -----------------------------------------------------------------------


def test_ending_the_link_refuses_the_session_with_its_own_reason() -> None:
    link = LinkState()
    assert link.end() is False
    link.claim(link.issue_code(), "a")
    assert link.end() is True
    assert link.refusal("a") == ENDED
    status = link.status()
    assert status["linked"] is False and status["ended"] == "ended"
    link.claim(link.issue_code(), "b")
    assert link.status()["ended"] is None and link.refusal("b") is None


def test_the_link_ends_after_the_last_spyglass_window_closes() -> None:
    clock = [datetime(2026, 10, 15, 8, tzinfo=UTC)]
    link = LinkState(now=lambda: clock[0])
    link.claim(link.issue_code(), "a")
    link.dashboard_seen()
    clock[0] += timedelta(seconds=5)
    link.window_closed()
    clock[0] += timedelta(seconds=60)
    assert link.refusal("a") is None  # still within the grace period
    clock[0] += timedelta(seconds=31)
    assert link.refusal("a") == CLOSED
    assert link.status()["ended"] == "closed"


def test_a_reload_or_another_open_window_keeps_the_link() -> None:
    clock = [datetime(2026, 10, 15, 8, tzinfo=UTC)]
    link = LinkState(now=lambda: clock[0])
    link.claim(link.issue_code(), "a")
    link.window_closed()
    clock[0] += timedelta(seconds=2)
    link.dashboard_seen()  # the reloaded page, or another window, checks in
    clock[0] += timedelta(minutes=10)
    assert link.refusal("a") is None and link.status()["linked"] is True


def test_the_dashboard_can_end_the_link(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        link = client.app.state.service_state.link
        link.claim(link.issue_code(), "a")
        assert client.post("/api/link/end", content=b"{}").status_code == 415
        ended = client.post("/api/link/end", json={}).json()
        assert ended["linked"] is False and ended["ended"] == "ended"
        assert link.refusal("a") == ENDED
        assert client.post("/api/link/window-closed", json={}).status_code == 204


def test_the_link_prompt_says_what_to_do_when_the_session_opened_outside_the_vault() -> None:
    assert "did not open in the vault folder" in link_prompt("abc123")
