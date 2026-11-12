"""The work the radar scheduler runs: cycle stages, the capture poll and outcome records.

Kept apart from `scheduler.RadarScheduler` (which owns timing, locking and lifecycle) so each
file stays readable. `StagesMixin` expects the scheduler's attributes: `_engine`, `_settings`,
`_get_index`, `_overrides`, `_stop_event`, `_state_lock`, `_brief_day`, `_force_watch`,
`_last_brief`, `_last_check` and the method `kick_assessment`.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from spyglass_service.radar.models import utcnow
from spyglass_service.radar.scheduler_support import stage_outcome

logger = logging.getLogger(__name__)

Stage = Callable[[], Any]


class StagesMixin:
    """Stage implementations, the capture poll and the brief/check records of the scheduler."""

    # ---- stages ---------------------------------------------------------------------------

    def _stage(self, name: str) -> Stage:
        """The callable for a stage: the test override, else the real implementation."""
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self, f"_do_{name}")

    def _do_legacy(self) -> Any:
        """The engine's feed and Raindrop collectors."""
        from spyglass_service.radar.sources.legacy import run_legacy_collection

        return run_legacy_collection(self._engine, self._settings)

    def _do_radar(self) -> Any:
        """The radar collectors (the watch sweep only when due, or when the reader forced it)."""
        from spyglass_service.radar.sources import collect_all

        return collect_all(self._engine, self._settings, force_watch=self._force_watch)

    def _do_raindrop(self) -> Any:
        """Mark Raindrop bookmarks as from-you."""
        from spyglass_service.radar.capture import mark_raindrop_captures

        return mark_raindrop_captures(self._engine)

    def _do_embed(self) -> Any:
        """Embed items that have no embedding yet."""
        from spyglass_service.embeddings import embed_pending

        return embed_pending(self._engine, self._get_index())

    def _do_pipeline(self) -> Any:
        """Assess pending items; stops between batches when the service is stopping."""
        from spyglass_service.radar.pipeline import run_pipeline

        return run_pipeline(self._engine, self._settings, self._get_index(),
                            should_stop=self._stop_event.is_set)

    def _do_watch(self) -> Any:
        """Link items to watched organisations and propose newly prominent ones.

        Runs after the pipeline, because linking by mention reads each item's assessment.
        """
        from spyglass_service.radar.watch.sweep import (
            link_mentions,
            link_watch_items,
            suggest_from_mentions,
        )

        return {
            "linked_by_search": link_watch_items(self._engine),
            "linked_by_mention": link_mentions(self._engine),
            "suggested": suggest_from_mentions(self._engine),
        }

    def _do_compose(self) -> Any:
        """Compose the brief of the day fixed when the cycle was started (today by default)."""
        from spyglass_service.radar.brief.compose import compose_brief

        compose_brief(self._engine, self._settings, self._get_index(), self._brief_day)
        return "composed"

    def _run_stages(self, names: list[str]) -> dict[str, dict]:
        """Run stages in order; a failing stage is recorded and never stops the next.

        A stop request ends the run before the next stage starts.
        """
        results: dict[str, dict] = {}
        for name in names:
            if self._stop_event.is_set():
                break
            try:
                results[name] = stage_outcome(name, self._stage(name)())
            except Exception as exc:  # noqa: BLE001 -- each stage is isolated
                logger.exception("radar stage %s failed", name)
                results[name] = {"ok": False, "status": "error",
                                 "detail": f"{type(exc).__name__}: {exc}"}
        return results

    # ---- capture poll ---------------------------------------------------------------------

    def poll_captures(self) -> dict[str, int]:
        """Pick up links sent in through Slack or Gmail; assess them when any arrived.

        Skipped while a cycle's Gmail or Slack collector holds the shared capture lock.
        """
        from spyglass_service.radar.sources._common import NotConfigured, capture_sources_lock

        if not capture_sources_lock.acquire(blocking=False):
            return {}
        counts: dict[str, int] = {}
        try:
            from spyglass_service.radar.sources.gmail import collect_gmail
            from spyglass_service.radar.sources.slack import collect_slack

            polls = (
                ("slack", lambda: collect_slack(self._engine, self._settings)),
                ("gmail", lambda: collect_gmail(
                    self._engine, self._settings, newsletters=False)["capture"]),
            )
            for name, poll in polls:
                try:
                    counts[name] = poll()
                except NotConfigured:
                    continue
                except Exception:  # noqa: BLE001 -- a bad poll is retried at the next poll
                    logger.exception("capture poll %s failed", name)
        finally:
            capture_sources_lock.release()
        if sum(counts.values()):
            self.kick_assessment()
        return counts

    # ---- records for status() -------------------------------------------------------------

    def _set_last_brief(self, day: date, result: str, reason: str | None = None) -> None:
        """Remember the latest brief attempt."""
        record = {"day": day.isoformat(), "result": result, "at": utcnow().isoformat()}
        if reason:
            record["reason"] = reason
        with self._state_lock:
            self._last_brief = record

    def _record_brief(self, day: date, stage: dict | None) -> None:
        """Record how the compose stage of a cycle went."""
        if stage is None:
            self._set_last_brief(day, "skipped", "The service stopped before the brief was "
                                                 "composed; the next check will compose it.")
        elif stage["ok"]:
            self._set_last_brief(day, "ok")
        else:
            self._set_last_brief(day, "error", f"{stage['detail']} The next check will try again.")

    def _set_last_check(self, now: datetime, result: str) -> None:
        """Remember the latest catch-up check."""
        with self._state_lock:
            self._last_check = {"at": now.isoformat(), "result": result}
