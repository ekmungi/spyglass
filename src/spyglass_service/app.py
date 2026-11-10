"""FastAPI application factory: lifespan, health, refresh, activity, SPA serving."""

import asyncio
import logging
import webbrowser
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

from spyglass_service import __version__
from spyglass_service.api_briefs import router as briefs_router
from spyglass_service.api_cards import router as cards_router
from spyglass_service.api_content import router as content_router
from spyglass_service.api_feeds import router as feeds_router
from spyglass_service.api_inbox import router as inbox_router
from spyglass_service.api_jobs import router as jobs_router
from spyglass_service.api_link import router as link_router
from spyglass_service.api_pages import router as pages_router
from spyglass_service.api_settings import router as settings_router
from spyglass_service.api_taxonomy import router as taxonomy_router
from spyglass_service.backup import backup_db
from spyglass_service.brief import compose_due_briefs
from spyglass_service.cards import materialize_cards
from spyglass_service.categories import migrate_categories_once, migrate_group_label_to_category
from spyglass_service.collectors.factory import build_collectors
from spyglass_service.config import Settings, apply_overlay
from spyglass_service.db import backfill_rss_feed_urls, check_db_integrity, create_db_engine, init_db
from spyglass_service.documents import set_yt_transcribe_cmd
from spyglass_service.yt_discovery import discover_yt_transcribe
from spyglass_service.embeddings import EmbeddingIndex, embed_pending_all
from spyglass_service.enrich import enrich_item, run_scheduled_enrich
from spyglass_service.claude_jobs import reset_interrupted as reset_interrupted_claude_jobs
from spyglass_service.fetch_worker import FetchWorker, JobRunner, reset_interrupted
from spyglass_service.job_worker import ClaudeJobWorker
from spyglass_service.claude_link import (
    DEFAULT_PROMPT,
    LinkOpener,
    card_titles,
    default_opener,
    name_cards,
    session_link,
)
from spyglass_service.mcp_register import ensure_mcp_registration
from spyglass_service.request_guards import (
    ALLOWED_ORIGIN,
    ALLOWED_ORIGIN_REGEX,
    CrossSiteGuard,
    require_json,
)
from spyglass_service.mcp_server import ServiceState, build_mcp
from spyglass_service.skill_sync import default_repo_skills_dir, sync_skills
from spyglass_service.migrate_data_dir import migrate_data_dir
from spyglass_service.models import RunLog
from spyglass_service.rebucket import (
    _rebucket_marker_done,
    _set_rebucket_marker,
    rebucket_recent_briefs,
)
from spyglass_service.recategorize import is_recategorize_running, run_recategorize
from spyglass_service.refresh import is_stale, run_refresh
from spyglass_service.single_writer import SingleWriter


class SelectionPayload(BaseModel):
    """Dashboard multi-select body: which cards a Claude session should pick up.

    open_card_id, when sent, is the item open in the reader ("this one" in the linked session);
    an older dashboard that omits it leaves the open item as it was.
    """

    card_ids: list[int]
    open_card_id: int | None = None


class LaunchPayload(BaseModel):
    """Open-in-Claude body: optional prompt for the new Claude desktop session.

    model is accepted for older dashboards and ignored: a claude:// link has no model
    parameter, so the desktop app's own model picker applies.
    """

    prompt: str | None = None
    model: str | None = None
    # False for a job (Process inbox): the prompt does not name the cards ticked in the Workspace.
    include_selection: bool = True


# Shown at / when the frontend has not been built yet; never a white screen.
_PLACEHOLDER = (
    "<html><body><h1>Spyglass</h1>"
    "<p>The service is running, but no dashboard build was found.</p></body></html>"
)


logger = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    shutdown_handler: Callable[[], None] | None = None,
    spa_dir: Path | None = None,
    link_opener: LinkOpener | None = None,
    open_external: Callable[[str], None] | None = None,
    index: EmbeddingIndex | None = None,
    skip_startup_embed: bool = False,
    fetch_runner: JobRunner | None = None,
    skip_fetch_worker: bool = False,
    claude_worker: ClaudeJobWorker | None = None,
    skip_claude_worker: bool = False,
) -> FastAPI:
    """Build the Spyglass FastAPI app.

    settings: runtime configuration. shutdown_handler: called by POST /api/shutdown
    so the host process (the Obsidian plugin's child) can stop gracefully.
    spa_dir: directory holding the built frontend; a placeholder page is served
    when it does not exist.
    open_external: callable used by POST /api/cards/{id}/open-external to open the
    item url in the host browser. Defaults to webbrowser.open. Injected for testing
    so the real browser is never opened during the test suite.
    index: optional pre-built embedding index; if None, ServiceState builds one lazily
    on first call to ensure_index().
    skip_startup_embed: when True the lifespan does NOT fire _schedule_embed at startup.
    Use in tests that manually control the embed/categorize pass to prevent background
    threadpool races against test-seeded data.
    fetch_runner: what a queued full-text fetch actually does. Defaults to the
    enrichment cascade with the relevance gate bypassed; injected in tests so the queue can be
    exercised without the network or an LLM.
    skip_fetch_worker: when True the fetch worker thread is created but never started, so
    API tests can assert on queued state without a live worker racing them to completion.
    claude_worker: the background-job worker; built from the settings when None, so tests
    can inject one with a fake Claude run. skip_claude_worker: create it but never start it.
    """

    # Dashboard-edited settings overlay the env config on every start.
    settings = apply_overlay(settings)
    # Resolve the yt-transcribe CLI once (explicit setting or auto-discovery) so video
    # full-text finds the binary even when ~/.local/bin is not on the service's PATH.
    set_yt_transcribe_cmd(settings.yt_transcribe_cmd or discover_yt_transcribe(settings.vault_path))
    # Engine and shared state are created eagerly so the MCP server can bind to
    # them at construction time; the schema is created during startup.
    engine = create_db_engine(settings.db_path)
    state = ServiceState(settings=settings, engine=engine, index=index)
    mcp_app = build_mcp(state).http_app(path="/")

    def _default_fetch_runner(card_id: int) -> None:
        """Run the enrichment cascade for one queued card, bypassing the relevance gate.

        A queued job only ever exists because the user explicitly asked for this card's
        full text, so the Gate-1 cutoff is bypassed exactly as the old synchronous
        endpoint did.
        """
        enrich_item(engine, state.ensure_index(), settings, card_id, bypass_gate=True)

    # One serial background worker drains on-demand fetches, so a
    # fetch's progress lives in the DB instead of in the reader pane's React state --
    # which the dashboard destroys the moment another card is opened.
    fetch_worker = FetchWorker(engine, fetch_runner or _default_fetch_runner)
    # Hidden Claude runs for Prepare detail and File it. It opens Obsidian through the
    # same opener as the dashboard's links, looked up at call time so tests can swap it.
    job_worker = claude_worker or ClaudeJobWorker(
        engine, settings, opener=lambda url: app.state.link_opener(url))

    # Background shallow embedding. Held in a set so the task is not GC'd before it runs.
    _embed_tasks: set[asyncio.Task] = set()
    # Serialize the Daily Brief compose so two overlapping passes (startup +
    # an on-open refresh, or two rapid refreshes) can never both compose the same un-briefed
    # day. compose_due_briefs is idempotent by day, but between reading eligibility and
    # stamping, a concurrent pass could pick the same day -- the gate makes the second a skip.
    _compose_gate = SingleWriter()

    def _compose_due_briefs_guarded() -> None:
        """Compose every due publish-day brief, at most one pass at a time.

        compose_due_briefs self-limits to un-briefed days (a repeated pass is a no-op, no
        LLM call, once caught up) and pauses per bucket internally -- an LLM failure on one
        day is logged and skipped there, never raised. The single-writer gate additionally
        stops an overlapping refresh/startup pass from double-composing a day."""
        _compose_gate.run(lambda: compose_due_briefs(engine, state.ensure_index(), settings))

    def _schedule_embed(force_enrich: bool = False) -> None:
        """Embed pending items, then run the enrichment pass, off the event loop.

        force_enrich=True (the refresh path, when new items arrived) bypasses the daily
        guard so freshly-collected cards are judged promptly."""
        def _work() -> None:
            embed_pending_all(engine, state.ensure_index())  # keeps blurb coverage
            # Enrichment cascade: guarded to <= once/day at startup, forced on a
            # refresh that brought in new items. No Claude session.
            run_scheduled_enrich(engine, state.ensure_index(), settings, force=force_enrich)
            # Daily Brief: compose every due publish-day brief AFTER
            # enrichment so freshly-judged cards make the same day's brief (guarded).
            _compose_due_briefs_guarded()

        task = asyncio.create_task(run_in_threadpool(_work))
        _embed_tasks.add(task)
        task.add_done_callback(_embed_tasks.discard)

    def _schedule_compose() -> None:
        """Run a guarded compose pass off the event loop, without the embed/enrich work.

        On-open trigger: fired when a refresh skips collection because data is
        still fresh -- a local publish-day may have closed since the last pass, so compose
        any newly-due day now rather than waiting for a restart or the next stale refresh.
        Idempotent + single-writer gated: a no-op (no LLM) when nothing is due, a skip when
        a compose is already running."""
        task = asyncio.create_task(run_in_threadpool(_compose_due_briefs_guarded))
        _embed_tasks.add(task)
        task.add_done_callback(_embed_tasks.discard)

    # Background Recategorize pass. Held in a set so the task is not GC'd mid-run.
    _recat_tasks: set[asyncio.Task] = set()

    def _kick_recategorize() -> None:
        """Run the Recategorize pass off the event loop (fire-and-forget, like _schedule_embed).

        run_recategorize writes its own RunLog('recategorize') -- 'running' at the start and the
        JSON result at the end -- which the Settings UI polls via GET /api/recategorize. It never
        raises, so a naming-LLM failure cannot take down the background task."""
        def _work() -> None:
            run_recategorize(engine, state.ensure_index(), settings)

        task = asyncio.create_task(run_in_threadpool(_work))
        _recat_tasks.add(task)
        task.add_done_callback(_recat_tasks.discard)

    async def _run_backup() -> None:
        """Snapshot the DB into the rotating backups dir; never breaks the caller.

        The blocking VACUUM INTO runs in the threadpool (off the event loop). A
        backup failure is recorded as a RunLog row -- visible in the Activity feed
        -- instead of raised, so a bad backup can never take down startup or a
        refresh. The DB has no other safety net (see the corruption incident).
        """
        try:
            await run_in_threadpool(
                backup_db,
                settings.db_path,
                backups_dir=settings.backups_dir,
                keep=settings.backup_keep,
            )
        except Exception as exc:
            with Session(engine) as session:
                session.add(
                    RunLog(
                        source="backup",
                        status="error",
                        detail=str(exc),
                        finished_at=datetime.now(UTC),
                    )
                )
                session.commit()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # One-time relocation of operational state to ~/.spyglass, before the DB opens.
        migrate_data_dir(settings.data_dir)
        # Surface a corrupt DB via /api/health instead of crash-looping: check
        # integrity BEFORE init_db (init_db itself raises on a malformed file), and skip every
        # DB-dependent startup step when it fails.
        app.state.db_ok = check_db_integrity(engine)
        if app.state.db_ok:
            init_db(engine)
            # One-time migration: reset any RECENT pre-publish-day-windowing
            # briefs (un-stamp their cards + delete the rows) so the compose trigger
            # below rebuilds them into proper per-day briefs. Guarded to run exactly
            # once, ever -- must happen before _schedule_embed's compose_due_briefs
            # call on THIS startup, or the reset cards would sit unbriefed until the
            # next pass instead of being immediately re-bucketed.
            if not _rebucket_marker_done(engine):
                rebucket_recent_briefs(engine)
                _set_rebucket_marker(engine)
            # Snapshot the just-initialized DB before anything mutates it this run.
            await _run_backup()
            # Backfill Item.feed_url for RSS items collected before 0.13.0.
            # reader.db holds the authoritative entry→feed mapping; this is a no-op on
            # a fresh install or when reader.db does not yet exist.
            backfill_rss_feed_urls(engine, settings.data_dir / "reader.db")
            # Backfill cards for any items collected before the card model existed,
            # so an upgraded DB shows its items immediately.
            materialize_cards(engine)
            # One-time unify: existing group_label clusters become categories.
            migrate_group_label_to_category(engine)
            # One-time: seed the user-owned category set and fold drifted labels onto it.
            # Guarded (runs once) so it never re-seeds a bucket the user later removes in Settings.
            migrated = migrate_categories_once(engine)
            if migrated:
                logger.info("Category consolidation applied: %s", migrated)
            # Load any persisted vectors, then backfill missing ones in the background.
            state.ensure_index().load_from_db(engine)
            if not skip_startup_embed:
                _schedule_embed()
            # A job left `running` means the service died mid-fetch. Fail it
            # before the worker starts, so it is visible rather than stuck forever.
            reset_interrupted(engine)
            # A Claude job left running died with the previous service; fail it.
            reset_interrupted_claude_jobs(engine)
            if not skip_claude_worker:
                job_worker.start()
            if not skip_fetch_worker:
                fetch_worker.start()
        else:
            logger.warning(
                "DB integrity check failed for %s; serving in degraded mode -- restore from a "
                "backup in %s",
                settings.db_path,
                settings.backups_dir,
            )
        # Mirror the repo's bundled skills into the vault's .claude/skills so a
        # dashboard-launched session always loads the current instructions.
        # Independent of the DB; non-fatal (sync_skills swallows per-skill IO errors).
        if settings.vault_path:
            synced = sync_skills(default_repo_skills_dir(), settings.vault_path)
            if synced:
                logger.info("Synced bundled skills into the vault: %s", ", ".join(synced))
            # A Claude desktop session opened in the vault finds Spyglass through the vault's
            # .mcp.json; keep its spyglass entry present. Non-fatal.
            if settings.register_mcp and ensure_mcp_registration(settings.vault_path, settings.port):
                logger.info("Registered the spyglass MCP server in the vault's .mcp.json")
        # The mounted MCP app needs its own lifespan run inside ours.
        async with mcp_app.lifespan(app):
            yield
        # Stop the worker before disposing the engine -- it holds sessions against it.
        fetch_worker.stop()
        job_worker.stop()
        engine.dispose()

    app = FastAPI(title="Spyglass", version=__version__, lifespan=lifespan)
    # The Obsidian plugin calls the API from origin app://obsidian.md, and the
    # dashboard may be opened in a plain browser tab on localhost -- both are
    # cross-origin, so allow exactly those (no credentials, localhost-only tool).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_origin_regex=ALLOWED_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # CORS only stops a foreign page from reading a reply; this stops its POST from running at
    # all. Added after CORS, so it runs before CORS sees the request.
    app.add_middleware(CrossSiteGuard)
    # A page that points its own domain at 127.0.0.1 could otherwise read every reply; its requests
    # still carry that domain in the Host header. Added after the guard above, so it runs first.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.state.settings = settings
    app.state.engine = engine
    app.state.service_state = state
    # The manual /briefs/generate endpoint (a separate router) composes
    # through this same gate (exclusive/blocking) so it can't race a background compose
    # into a double-composed day.
    app.state.compose_gate = _compose_gate
    # The content router wakes this after enqueuing so a click is picked up
    # immediately rather than at the next poll.
    app.state.fetch_worker = fetch_worker
    app.state.claude_worker = job_worker
    app.state.open_external = open_external or webbrowser.open
    # Hands claude:// and obsidian:// links to the operating system; injectable for tests.
    app.state.link_opener = link_opener or default_opener
    app.mount("/mcp", mcp_app)
    app.include_router(briefs_router)
    app.include_router(cards_router)
    app.include_router(content_router)
    app.include_router(feeds_router)
    app.include_router(inbox_router)
    app.include_router(link_router)
    app.include_router(jobs_router)
    app.include_router(pages_router)
    app.include_router(settings_router)
    app.include_router(taxonomy_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Liveness probe polled by the Obsidian plugin's supervision loop.

        Reports degraded (still HTTP 200) when the DB failed its startup integrity check, so the
        plugin/dashboard can show the problem rather than the service crash-looping.
        """
        db_ok = getattr(app.state, "db_ok", True)
        return {
            "status": "ok" if db_ok else "degraded",
            "version": __version__,
            "db": "ok" if db_ok else "unhealthy",
        }

    @app.post("/api/shutdown", status_code=202)
    def shutdown() -> dict[str, str]:
        """Request a graceful stop of the host process."""
        if shutdown_handler is not None:
            shutdown_handler()
        return {"status": "stopping"}

    @app.post("/api/refresh")
    async def refresh(if_stale: bool = False) -> dict:
        """Run all configured collectors; with if_stale, only when data is old.

        Collection is blocking I/O, so it runs in the threadpool. A summary row
        is always logged so staleness has a reference point even with 0 sources.

        Refused with 409 when the DB failed its integrity check: writing,
        embedding, or VACUUM-INTO-backing a malformed DB would make things worse. The
        plugin's auto-refresh treats a non-200 here as a failure and backs off.
        """
        if not getattr(app.state, "db_ok", True):
            raise HTTPException(status_code=409, detail="database degraded; restore from a backup")
        engine = app.state.engine
        max_age = timedelta(hours=settings.stale_hours)
        if if_stale and not is_stale(engine, max_age):
            # Data is still fresh so collection is skipped, but a local publish-day may have
            # closed since the last pass -- compose any newly-due brief now so
            # opening the app fills it without a restart. Idempotent + single-writer gated.
            _schedule_compose()
            return {"refreshed": False, "sources": 0}
        collectors = build_collectors(settings, engine)
        new_count = await run_in_threadpool(run_refresh, engine, collectors)
        with Session(engine) as session:
            session.add(
                RunLog(
                    source="refresh",
                    status="ok",
                    detail=f"{len(collectors)} sources",
                    finished_at=datetime.now(UTC),
                )
            )
            session.commit()
        # Judge freshly-collected items now (force past the daily guard) so they
        # don't sit unjudged until the next restart -- but only when new items arrived.
        _schedule_embed(force_enrich=new_count > 0)
        await _run_backup()  # Snapshot the DB now that a refresh has changed it.
        return {"refreshed": True, "sources": len(collectors)}

    @app.post("/api/recategorize", status_code=202)
    async def recategorize() -> dict:
        """Kick the background Recategorize pass: re-assign the Unsorted pile to
        the current categories, then cluster the remainder into candidate new categories.

        Fire-and-forget on the threadpool so the request returns immediately; the Settings UI
        polls GET /api/recategorize for progress + candidates. Refused with 409 on a degraded DB
        (never write to a malformed DB), and guarded so a second click while a run is
        already in flight is a no-op rather than a duplicate pass.
        """
        if not getattr(app.state, "db_ok", True):
            raise HTTPException(status_code=409, detail="database degraded; restore from a backup")
        if is_recategorize_running(engine):
            return {"status": "already_running"}
        _kick_recategorize()
        return {"status": "started"}

    @app.post("/api/selection", dependencies=[Depends(require_json)])
    def set_selection(payload: SelectionPayload) -> dict:
        """Record the dashboard's multi-select for pickup by a Claude session."""
        state.set_selection(payload.card_ids)
        if "open_card_id" in payload.model_fields_set:
            state.open_card_id = payload.open_card_id
        return {"card_ids": state.selection, "open_card_id": state.open_card_id}

    @app.post("/api/open-claude", response_model=None, dependencies=[Depends(require_json)])
    def open_claude(payload: LaunchPayload) -> dict | JSONResponse:
        """Open a new Claude desktop session (Code tab) in the vault, prompt typed in.

        The selected cards are named in the prompt; a prompt too long for a link becomes a
        hand-off the session fetches with get_handoff. 502 with the full prompt when the
        desktop app cannot be opened, so the dashboard can offer to copy it instead.
        """
        if settings.vault_path is None:
            raise HTTPException(status_code=409, detail="vault_path is not configured")
        cards = card_titles(engine, state.selection) if payload.include_selection else []
        prompt = name_cards(payload.prompt or DEFAULT_PROMPT, cards)
        url = session_link(prompt, settings.vault_path, state.handoffs)
        try:
            app.state.link_opener(url)
        except Exception:  # noqa: BLE001 -- any failure to open means "not available"
            logger.warning("Could not open the Claude desktop app", exc_info=True)
            return JSONResponse(
                status_code=502, content={"error": "claude_desktop_unavailable", "prompt": prompt}
            )
        return {"opened": True}

    @app.get("/api/selection")
    def get_selection() -> dict:
        """Current selection; empty before the user selects anything."""
        updated = state.selection_updated_at
        return {
            "card_ids": state.selection,
            "open_card_id": state.open_card_id,
            "updated_at": updated.isoformat() if updated else None,
        }

    @app.get("/api/runs")
    def runs(limit: int = 100) -> list[dict]:
        """Activity feed: latest runs first, for the dashboard's Activity tab."""
        if not getattr(app.state, "db_ok", True):
            raise HTTPException(status_code=409, detail="database degraded; restore from a backup")
        with Session(app.state.engine) as session:
            rows = session.exec(
                select(RunLog)
                .order_by(RunLog.started_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            ).all()
        return [row.model_dump(mode="json") for row in rows]

    index_file = spa_dir / "index.html" if spa_dir is not None else None
    if index_file is not None and index_file.is_file():
        assets_dir = spa_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/")
        def spa_index() -> FileResponse:
            """Serve the built dashboard's entry point."""
            return FileResponse(index_file)

    else:

        @app.get("/")
        def placeholder() -> HTMLResponse:
            """Plain informational page until the frontend build exists."""
            return HTMLResponse(_PLACEHOLDER)

    return app
