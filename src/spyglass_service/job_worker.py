"""The thread that runs background jobs, one at a time.

Before a filing job it makes sure Obsidian is running: a move must go
through Obsidian for links and the note's comments to follow the note. When Obsidian is closed,
Spyglass opens it and waits until it answers.
"""

import logging
import threading
import time
from datetime import UTC, datetime
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import Engine

from sqlmodel import Session

from spyglass_service import claude_jobs as jobs
from spyglass_service.config import Settings
from spyglass_service.detail_notes import in_spyglass_folder, relocate_note
from spyglass_service.models import Card

logger = logging.getLogger(__name__)

Runner = Callable[..., jobs.RunOutcome]


# How long the worker waits for the service's own address before its first job: queued jobs
# from the last session would otherwise start before the MCP endpoint answers.
SERVICE_WAIT_S = 60.0


def obsidian_running(url: str) -> bool:
    """Whether Obsidian answers at its local address: any HTTP answer counts, even a refusal
    to an unauthenticated request. Proxy settings are ignored: this is the user's own PC."""
    try:
        httpx.get(url, timeout=2.0, verify=False, trust_env=False)  # noqa: S501 -- loopback probe
    except httpx.TransportError:
        return False
    return True


class ClaudeJobWorker:
    """One worker thread draining the job queue; `wake()` after queuing starts it at once."""

    def __init__(self, engine: Engine, settings: Settings, opener: Callable[[str], None],
                 run: Runner = jobs.run_claude,
                 probe: Callable[[str], bool] = obsidian_running,
                 sleep: Callable[[float], None] = time.sleep,
                 poll_interval: float = 5.0) -> None:
        self._engine = engine
        self._settings = settings
        # The port the service is running on: a port changed in Settings applies only after a
        # restart, so runs must not follow it before then.
        self._port = settings.port
        # Set when Claude reported the user's usage limit: no job starts before this time.
        self.paused_until: datetime | None = None
        self._now = lambda: datetime.now(UTC)
        self._opener = opener
        self._run = run
        self._probe = probe
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="spyglass-claude-jobs",
                                        daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the worker; a running Claude process is ended within about a second."""
        self._stopping.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def _wait_for_service(self) -> None:
        """Wait until the service's own address answers, so a run can reach its MCP tools."""
        url = f"http://127.0.0.1:{self._port}/api/health"
        waited = 0.0
        while waited < SERVICE_WAIT_S and not self._stopping.is_set():
            if self._probe(url):
                return
            self._sleep(1.0)
            waited += 1.0

    def _loop(self) -> None:
        self._wait_for_service()
        while not self._stopping.is_set():
            try:
                while not self._stopping.is_set() and self.run_one() is not None:
                    pass
            except Exception:  # noqa: BLE001 -- the only job worker must outlive one bad pass
                logger.exception("claude job pass failed")
            self._wake.wait(timeout=self._poll_interval)
            self._wake.clear()

    def run_one(self) -> dict | None:
        """Run the oldest queued job to its end; None when the queue is empty or paused for the
        user's Claude limit. Whatever goes wrong, the job ends failed with the reason: it never
        stays running."""
        if self.paused_until is not None:
            if self._now() < self.paused_until:
                return None
            self.paused_until = None
        job = jobs.claim_next(self._engine)
        if job is None:
            return None
        try:
            return self._run_job(job)
        except Exception as exc:  # noqa: BLE001 -- a job must end, whatever broke
            logger.exception("claude job %s failed in Spyglass", job.id)
            return jobs.fail(self._engine, job.id, f"Spyglass hit an error running the job: {exc}")
        finally:
            if job.kind == jobs.FILE:
                # A filing run may have moved the note and then failed to report it.
                relocate_note(self._settings, self._engine, job.card_id, force=True)

    def _still_needed(self, job) -> str | None:
        """Why a job no longer makes sense when its turn comes, or None."""
        with Session(self._engine) as session:
            card = session.get(Card, job.card_id)
            note = card.briefing_path if card else None
        if card is None:
            return "The item no longer exists."
        has_note = bool(note) and Path(note).is_file()
        if job.kind == jobs.PREPARE and has_note:
            return "This item already has a note."
        if job.kind == jobs.FILE and not (has_note and in_spyglass_folder(self._settings, note)):
            return "The note is already filed in your own folders, so there is nothing to file."
        return None

    def _run_job(self, job) -> dict:
        settings = self._settings
        if settings.vault_path is None:
            return jobs.fail(self._engine, job.id, "Set the vault folder in Settings first.")
        reason = self._still_needed(job)
        if reason is not None:
            return jobs.fail(self._engine, job.id, reason)
        claude = jobs.find_claude(settings)
        if claude is None:
            return jobs.fail(self._engine, job.id,
                             "Claude Code was not found. Install it, or set its path in Settings "
                             "(Claude command).")
        try:
            if job.kind == jobs.FILE:
                # Spyglass itself asks this server to move the note, so fail now,
                # in words, rather than after a Claude run has chosen a folder.
                jobs.find_obsidian_server(settings)
            config = jobs.mcp_config_file(settings, self._port, job.kind)
        except jobs.ObsidianServerMissing as exc:
            return jobs.fail(self._engine, job.id, str(exc))
        if job.kind == jobs.FILE:
            ready = self._ensure_obsidian(job.id)
            if ready == "cancelled":
                return jobs.finish(self._engine, job.id,
                                   jobs.RunOutcome(None, "", "", cancelled=True), 0)
            if ready != "ready":
                return jobs.fail(self._engine, job.id,
                                 f"Obsidian did not answer within {settings.obsidian_wait_seconds} "
                                 f"seconds at {settings.obsidian_probe_url}, so the note was not "
                                 "filed. Open Obsidian, check that address in Settings, and try "
                                 "again.")
        if jobs.cancel_requested(self._engine, job.id):
            return jobs.finish(self._engine, job.id,
                               jobs.RunOutcome(None, "", "", cancelled=True), 0)
        jobs.set_progress(self._engine, job.id, "Claude is working")
        try:
            command = jobs.build_command(settings, claude, job.kind, config)
            outcome = self._run(
                command, cwd=settings.vault_path,
                timeout_s=settings.job_timeout_minutes * 60,
                should_stop=lambda: (self._stopping.is_set()
                                     or jobs.cancel_requested(self._engine, job.id)),
                prompt=jobs.job_prompt(job.id, job.kind, job.card_id))
        except OSError as exc:
            return jobs.fail(self._engine, job.id, f"Claude Code could not start: {exc}")
        if outcome.cancelled and self._stopping.is_set():
            return jobs.fail(self._engine, job.id,
                             "Spyglass stopped while this job was running. Try again.")
        reset = None if jobs.get_job(self._engine, job.id).reported else \
            jobs.limit_reset(outcome, jobs.parse_result(outcome.stdout), self._now())
        if reset is not None:
            # The user's Claude limit is reached: this job and the rest of the queue wait for
            # the reset rather than all failing.
            self.paused_until = reset
            logger.info("Claude usage limit reached; jobs wait until %s", reset.isoformat())
            return jobs.requeue_for_limit(self._engine, job.id, reset)
        return jobs.finish(self._engine, job.id, outcome, settings.job_timeout_minutes)

    def _ensure_obsidian(self, job_id: int) -> str:
        """Open Obsidian when it is closed, and wait until it answers: "ready", "cancelled" or
        "timeout"."""
        url = self._settings.obsidian_probe_url
        if self._probe(url):
            return "ready"
        jobs.set_progress(self._engine, job_id, "Opening Obsidian")
        vault = self._settings.vault_path
        try:
            self._opener(f"obsidian://open?vault={quote(vault.name if vault else '')}")
        except OSError as exc:
            logger.warning("could not open Obsidian: %s", exc)
            return "timeout"
        waited = 0.0
        step = 2.0
        while waited < self._settings.obsidian_wait_seconds and not self._stopping.is_set():
            if jobs.cancel_requested(self._engine, job_id):
                return "cancelled"
            self._sleep(step)
            waited += step
            if self._probe(url):
                return "ready"
        return "timeout"
