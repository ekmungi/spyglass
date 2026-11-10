# src/spyglass_service/single_writer.py
"""A non-blocking single-writer gate: at most one guarded call runs at a time.

Used to serialize the Daily Brief compose pass. compose_due_briefs is idempotent by
un-briefed day, but two passes that overlap (e.g. the startup enrichment pass and an
on-open refresh, or two rapid refreshes) could both read the same un-briefed day before
either stamps its cards -- and thus double-compose it (two briefs for one day plus a
wasted LLM call). This gate makes a second, concurrent compose a no-op: the pass already
running will cover every currently-due day, so the second caller skips immediately rather
than queueing behind it.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class SingleWriter:
    """Serialize the compose pass so at most one runs at a time.

    Two entry styles share one lock: `run()` for automatic/background triggers that
    should SKIP when a pass is already in flight (redundant work), and `exclusive()`
    for a user-initiated compose that MUST run and needs its result -- it WAITS for any
    in-flight pass, then runs. Both together guarantee a publish-day is never composed
    twice concurrently, whichever trigger fires.
    """

    def __init__(self) -> None:
        # A plain lock: run() try-acquires without blocking (skip if busy); exclusive()
        # acquires blocking (wait, then run). Same lock, so the two styles are mutually
        # exclusive against each other, not just against their own kind.
        self._lock = threading.Lock()

    def run(self, fn: Callable[[], object]) -> bool:
        """Run fn under the gate, or skip it if a guarded call is already in flight.

        Args:
            fn: The zero-arg callable to run while holding the gate.

        Returns:
            True if this call acquired the gate and ran fn; False if it skipped because
            another guarded call already held the gate (fn was NOT run).
        """
        if not self._lock.acquire(blocking=False):
            return False
        try:
            fn()
            return True
        finally:
            # Release even if fn raised, so a failed compose never wedges the gate.
            self._lock.release()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Block until the gate is free, hold it for the with-body, then release.

        For a caller that must run and needs its result (e.g. the manual "generate
        now" endpoint), unlike run() which skips when busy. Serializes behind any
        in-flight run()/exclusive() pass, so the manual compose can never race a
        background compose into a double-composed day.

        Yields:
            None -- the body runs while holding the gate.
        """
        self._lock.acquire()
        try:
            yield
        finally:
            # Release even if the body raised, so a failed compose never wedges the gate.
            self._lock.release()
