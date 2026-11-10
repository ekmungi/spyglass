# tests/test_briefs_api.py
"""Tests for the Daily Brief REST API and the post-enrich compose trigger.

compose_due_briefs is always mocked here -- these tests cover the HTTP contract (list,
detail, generate: composed / empty; recompose: happy / 404 / llm-down) and the startup
wiring that runs the compose pass after the enrichment pass.
"""

import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from spyglass_service.app import create_app
from spyglass_service.brief import BriefComposeError
from spyglass_service.config import Settings
from spyglass_service.models import Brief

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def _make_client(tmp_path: Path) -> TestClient:
    """TestClient with the startup embed/enrich pass disabled (no background races)."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    return TestClient(create_app(settings, skip_startup_embed=True))


def _seed_brief(
    engine,
    *,
    covers_until: datetime,
    markdown: str = "body",
    covers_from: datetime | None = None,
    publish_day: str = "",
    reviewed: bool = False,
    created_at: datetime | None = None,
) -> int:
    """Insert one Brief row and return its id.

    covers_from defaults to a 24h window ending at covers_until (the shape of legacy
    briefs, composed before publish-day windowing); publish_day/reviewed/created_at
    default to the legacy/unset values so existing callers seeding plain legacy briefs
    are unaffected.
    """
    with Session(engine) as session:
        brief = Brief(
            covers_from=covers_from if covers_from is not None else covers_until - timedelta(hours=24),
            covers_until=covers_until,
            markdown=markdown, item_count=2, low_count=1,
            publish_day=publish_day, reviewed=reviewed,
            **({"created_at": created_at} if created_at is not None else {}),
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        return brief.id


# ---------------------------------------------------------------------------
# GET /api/briefs + GET /api/briefs/{id}
# ---------------------------------------------------------------------------


def test_list_briefs_newest_first_with_title(tmp_path):
    """The list is newest-first and each row carries a human title (no markdown body)."""
    with _make_client(tmp_path) as client:
        engine = client.app.state.engine
        _seed_brief(engine, covers_until=NOW - timedelta(days=1), markdown="older")
        newer = _seed_brief(engine, covers_until=NOW, markdown="newer")
        r = client.get("/api/briefs")
        assert r.status_code == 200
        rows = r.json()
        assert [row["id"] for row in rows][0] == newer
        assert rows[0]["title"] == "Daily Brief — Jul 2, 2026"
        assert rows[0]["item_count"] == 2 and rows[0]["low_count"] == 1
        assert "markdown" not in rows[0]  # the list stays light; detail carries the body


def test_summary_title_legacy_brief_uses_covers_until_title(tmp_path):
    """Legacy briefs (publish_day == '') keep the OLD covers_until-based
    title derivation untouched -- existing briefs' display must not break."""
    with _make_client(tmp_path) as client:
        engine = client.app.state.engine
        bid = _seed_brief(engine, covers_until=NOW, publish_day="")
        r = client.get(f"/api/briefs/{bid}")
        assert r.status_code == 200
        body = r.json()
        assert body["title"] == "Daily Brief — Jul 2, 2026"
        assert body["publish_day"] == ""
        assert body["reviewed"] is False


def test_summary_title_single_day_brief(tmp_path):
    """A publish-day brief whose covers_from/until fall on the SAME local day gets the
    plain 'Daily Brief -- <day>' title, formatted from publish_day (not covers_until)."""
    with _make_client(tmp_path) as client:
        engine = client.app.state.engine
        # Both times sit mid-day UTC (not near midnight) so the machine-local timezone
        # conversion in local_day_of can't push either one across a calendar-day boundary.
        same_day_from = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)
        same_day_until = datetime(2026, 7, 3, 14, 0, tzinfo=UTC)
        bid = _seed_brief(
            engine, covers_from=same_day_from, covers_until=same_day_until,
            publish_day="2026-07-03", reviewed=True,
        )
        r = client.get(f"/api/briefs/{bid}")
        assert r.status_code == 200
        body = r.json()
        assert body["title"] == "Daily Brief — Jul 3, 2026"
        assert body["publish_day"] == "2026-07-03"
        assert body["reviewed"] is True


def test_summary_title_digest_brief_spanning_multiple_days(tmp_path):
    """A publish-day digest brief (covers a SPAN of days, publish_day is the newest day
    in that span) gets the 'Earlier -- through <day>' title instead of 'Daily Brief'."""
    with _make_client(tmp_path) as client:
        engine = client.app.state.engine
        span_from = datetime(2026, 6, 25, 1, 0, tzinfo=UTC)
        span_until = datetime(2026, 7, 1, 23, 0, tzinfo=UTC)
        bid = _seed_brief(
            engine, covers_from=span_from, covers_until=span_until,
            publish_day="2026-07-01",
        )
        r = client.get(f"/api/briefs/{bid}")
        assert r.status_code == 200
        body = r.json()
        assert body["title"] == "Earlier — through Jul 1, 2026"
        assert body["publish_day"] == "2026-07-01"


def test_list_briefs_sorted_by_publish_day_with_legacy_slotted_by_created_at(tmp_path):
    """The list sorts newest-first by the coalesced publish_day / created-at-local-day
    key -- a legacy brief (publish_day == '') is slotted by ITS created_at local day,
    not forced to the bottom just because its publish_day string is empty."""
    with _make_client(tmp_path) as client:
        engine = client.app.state.engine
        # Dated brief for the newest day.
        newest = _seed_brief(
            engine, covers_until=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
            publish_day="2026-07-03",
        )
        # Legacy brief (no publish_day) whose created_at sits BETWEEN the two dated
        # briefs -- it must sort there, not fall to the bottom via "" < any date string.
        middle = _seed_brief(
            engine, covers_until=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
            publish_day="", created_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        )
        # Dated brief for the oldest day.
        oldest = _seed_brief(
            engine, covers_until=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            publish_day="2026-07-01",
        )
        r = client.get("/api/briefs")
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()]
        assert ids == [newest, middle, oldest]


def test_get_brief_detail_includes_markdown(tmp_path):
    """The detail endpoint returns the full brief including its markdown."""
    with _make_client(tmp_path) as client:
        bid = _seed_brief(client.app.state.engine, covers_until=NOW, markdown="# Brief body")
        r = client.get(f"/api/briefs/{bid}")
        assert r.status_code == 200
        body = r.json()
        assert body["markdown"] == "# Brief body"
        assert body["title"] == "Daily Brief — Jul 2, 2026"


def test_get_unknown_brief_is_404(tmp_path):
    """An unknown brief id is a 404, not a 500."""
    with _make_client(tmp_path) as client:
        assert client.get("/api/briefs/9999").status_code == 404


# ---------------------------------------------------------------------------
# POST /api/briefs/generate
# ---------------------------------------------------------------------------


def test_generate_returns_composed_summaries(tmp_path, monkeypatch):
    """A manual generate runs compose_due_briefs and returns each composed brief's summary
    under {"composed": [...], "status": "composed"} (the multi-brief shape)."""
    import spyglass_service.api_briefs as api

    def fake_compose(engine, index, settings, **kwargs):
        return [
            Brief(id=7, covers_from=NOW - timedelta(hours=24), covers_until=NOW,
                  markdown="fresh", item_count=3, low_count=0, created_at=NOW,
                  publish_day="2026-07-02"),
            Brief(id=6, covers_from=NOW - timedelta(hours=48), covers_until=NOW - timedelta(hours=24),
                  markdown="older", item_count=1, low_count=2, created_at=NOW,
                  publish_day="2026-07-01"),
        ]

    monkeypatch.setattr(api, "compose_due_briefs", fake_compose)
    with _make_client(tmp_path) as client:
        r = client.post("/api/briefs/generate")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "composed"
        assert [row["id"] for row in body["composed"]] == [7, 6]
        # Light summary shape (no markdown body).
        assert body["composed"][0]["item_count"] == 3
        assert "markdown" not in body["composed"][0]
        # Both fake briefs composed; the real days_to_compose finds none due on the
        # empty test DB, so held clamps to 0 rather than going negative.
        assert body["held"] == 0


def test_generate_reports_empty_when_nothing_composed(tmp_path, monkeypatch):
    """compose_due_briefs returning [] with NOTHING due is an honest 200
    {"composed": [], "status": "empty", "held": 0} -- per-bucket pause replaces the
    global 503; held is 0 because no day was due in the first place."""
    import spyglass_service.api_briefs as api

    monkeypatch.setattr(api, "compose_due_briefs", lambda *a, **k: [])
    with _make_client(tmp_path) as client:
        r = client.post("/api/briefs/generate")
        assert r.status_code == 200
        assert r.json() == {"composed": [], "status": "empty", "held": 0}


def test_generate_reports_held_when_a_due_day_pauses(tmp_path, monkeypatch):
    """When a day IS due but its only bucket pauses (e.g. a heavy day the partition
    gate rejects), compose_due_briefs returns fewer briefs than there were due buckets.
    The endpoint reports the shortfall as `held` so the UI can say "1 day held" rather
    than the misleading "nothing to brief"."""
    import spyglass_service.api_briefs as api

    # One day is due; compose returns nothing (its only bucket paused).
    monkeypatch.setattr(api, "days_to_compose", lambda *a, **k: [date(2026, 7, 2)])
    monkeypatch.setattr(api, "compose_due_briefs", lambda *a, **k: [])
    with _make_client(tmp_path) as client:
        r = client.post("/api/briefs/generate")
        assert r.status_code == 200
        assert r.json() == {"composed": [], "status": "empty", "held": 1}


# ---------------------------------------------------------------------------
# POST /api/briefs/{id}/recompose
# ---------------------------------------------------------------------------


def test_recompose_returns_the_updated_brief(tmp_path, monkeypatch):
    """A recompose runs recompose_brief for that id and returns the full brief dict."""
    import spyglass_service.api_briefs as api

    captured = {}

    def fake_recompose(engine, index, settings, brief_id, **kwargs):
        captured["brief_id"] = brief_id
        return Brief(id=brief_id, covers_from=NOW - timedelta(hours=24), covers_until=NOW,
                     markdown="rebuilt", item_count=2, low_count=1, created_at=NOW)

    monkeypatch.setattr(api, "recompose_brief", fake_recompose)
    with _make_client(tmp_path) as client:
        r = client.post("/api/briefs/42/recompose")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == 42 and body["markdown"] == "rebuilt"
        assert captured["brief_id"] == 42


def test_recompose_unknown_brief_is_404(tmp_path):
    """Recomposing a brief that does not exist is a 404 (no LLM call, nothing written)."""
    with _make_client(tmp_path) as client:
        assert client.post("/api/briefs/9999/recompose").status_code == 404


def test_recompose_reports_503_when_llm_unavailable(tmp_path, monkeypatch):
    """An LLM failure during recompose is the same 503 llm_unavailable pause state."""
    import spyglass_service.api_briefs as api

    def boom(*a, **k):
        raise BriefComposeError("OpenRouter down")

    monkeypatch.setattr(api, "recompose_brief", boom)
    with _make_client(tmp_path) as client:
        r = client.post("/api/briefs/1/recompose")
        assert r.status_code == 503
        assert r.json()["detail"] == {"status": "llm_unavailable"}


# ---------------------------------------------------------------------------
# Startup trigger: embed -> enrich -> compose, and the pause swallow
# ---------------------------------------------------------------------------


def _wait_for(calls: list, sentinel: str, timeout: float = 5.0) -> None:
    """Poll until sentinel appears in calls (the background task runs on the app's loop)."""
    deadline = time.time() + timeout
    while sentinel not in calls and time.time() < deadline:
        time.sleep(0.02)


def test_startup_pass_runs_compose_after_enrich(tmp_path, monkeypatch):
    """The daily background pass runs compose_due_briefs AFTER the enrichment pass, so
    freshly-judged cards are eligible for the same day's brief."""
    import spyglass_service.app as app_module

    calls: list[str] = []
    monkeypatch.setattr(app_module, "embed_pending_all", lambda *a, **k: calls.append("embed"))
    monkeypatch.setattr(app_module, "run_scheduled_enrich", lambda *a, **k: calls.append("enrich"))
    monkeypatch.setattr(app_module, "compose_due_briefs", lambda *a, **k: calls.append("compose"))
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with TestClient(create_app(settings)):  # startup embed pass ENABLED
        _wait_for(calls, "compose")
    assert calls == ["embed", "enrich", "compose"]


def test_startup_runs_rebucket_reset_before_the_compose_trigger(tmp_path, monkeypatch):
    """The one-time re-bucket reset runs (synchronously, in lifespan)
    BEFORE compose_due_briefs fires (in the background embed/enrich/compose pass) on
    the SAME startup -- so cards freed by the reset are immediately eligible for the
    rebuild instead of waiting for a second startup."""
    import spyglass_service.app as app_module

    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "rebucket_recent_briefs", lambda *a, **k: calls.append("rebucket") or []
    )
    monkeypatch.setattr(app_module, "embed_pending_all", lambda *a, **k: calls.append("embed"))
    monkeypatch.setattr(app_module, "run_scheduled_enrich", lambda *a, **k: calls.append("enrich"))
    monkeypatch.setattr(app_module, "compose_due_briefs", lambda *a, **k: calls.append("compose"))
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with TestClient(create_app(settings)):  # startup embed pass ENABLED
        _wait_for(calls, "compose")
    assert calls == ["rebucket", "embed", "enrich", "compose"]


def test_startup_rebucket_reset_does_not_rerun_on_a_second_startup(tmp_path):
    """The guard marker persists in the DB, so a second app startup against the same
    database does not re-run the reset (idempotent across restarts, not just within
    one process)."""
    import spyglass_service.rebucket as rebucket_module

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    with TestClient(create_app(settings, skip_startup_embed=True)) as client:
        engine = client.app.state.engine
        assert rebucket_module._rebucket_marker_done(engine) is True

    # A second app instance pointed at the SAME db_path must see the marker already set
    # and skip the reset entirely.
    calls: list[str] = []
    import spyglass_service.app as app_module

    original = app_module.rebucket_recent_briefs
    try:
        app_module.rebucket_recent_briefs = lambda *a, **k: calls.append("rebucket") or original(*a, **k)
        with TestClient(create_app(settings, skip_startup_embed=True)):
            pass
    finally:
        app_module.rebucket_recent_briefs = original
    assert calls == []  # guarded: never called on the second startup
