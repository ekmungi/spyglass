"""Try several model providers in order for the bulk judging calls.

The reader may have more than one way to reach a model (OpenRouter, the Claude Code command, the
Gemini API, the Antigravity command). `call_with_fallback` tries the configured one first and, when it cannot be used right
now (out of credit, usage limit, not signed in, key missing, network down), the others named in
`radar_llm_fallback`, in order and never the same one twice. A reply that is not valid JSON is a
problem with the answer, not with the provider, so it is raised to the caller unchanged.

A provider that failed is remembered for ten minutes, so a pass over six hundred items asks a
provider that is out of credit once and not six hundred times. The call itself is injected
(`call_one(provider_name)`), which keeps this module independent of how each provider is reached.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from spyglass_service.radar.llm_errors import LlmUnavailable

logger = logging.getLogger(__name__)

__all__ = ["COOLDOWN_SECONDS", "COOLDOWNS", "PROVIDERS", "Cooldowns", "any_available",
           "call_with_fallback", "model_for_provider", "provider_order", "status"]

# How long a provider that could not be used is left alone. Ten minutes outlasts one pass over
# a large backlog and is short enough that a refilled account is noticed in the same morning.
COOLDOWN_SECONDS = 600.0
PROVIDERS = ("openrouter", "claude_code", "gemini", "antigravity")
_LABELS = {"openrouter": "OpenRouter", "claude_code": "Claude Code", "gemini": "Google Gemini",
           "antigravity": "Antigravity (your Google plan)"}
_OPENROUTER_MODEL = {"triage": "radar_triage_model", "digest": "radar_digest_model",
                     "writer": "radar_writer_model"}
_CLAUDE_MODEL = {"triage": "radar_claude_triage_model", "digest": "radar_claude_digest_model",
                 "writer": "radar_claude_writer_model"}
# Gemini has no per-role settings: one fast model that supports structured output serves all three.
GEMINI_BULK_MODEL = "gemini-3.8-flash"


class Cooldowns:
    """Which providers were unavailable recently, and why. Safe to use from several threads."""

    def __init__(self, clock: Callable[[], float] = time.time,
                 seconds: float = COOLDOWN_SECONDS) -> None:
        """`clock` returns seconds since the epoch; tests pass their own."""
        self._clock, self._seconds = clock, seconds
        self._lock = threading.Lock()
        self._down: dict[str, tuple[float, str]] = {}

    def mark(self, name: str, reason: str) -> None:
        """Remember that `name` could not be used, with the reason shown to the reader."""
        with self._lock:
            self._down[name] = (self._clock() + self._seconds, reason)

    def now(self) -> float:
        """The current time on this book's clock (epoch seconds)."""
        return self._clock()

    def until(self, name: str) -> float | None:
        """When the pause for `name` ends (epoch seconds), or None when it is not paused."""
        with self._lock:
            entry = self._down.get(name)
            if entry is None:
                return None
            if entry[0] <= self._clock():
                del self._down[name]
                return None
            return entry[0]

    def reason(self, name: str) -> str | None:
        """Why `name` is paused, or None."""
        with self._lock:
            entry = self._down.get(name)
        return entry[1] if entry and self.until(name) is not None else None

    def reset(self, name: str | None = None) -> None:
        """Forget one provider's pause (after the reader fixes it) or all of them."""
        with self._lock:
            if name is None:
                self._down.clear()
            else:
                self._down.pop(name, None)


COOLDOWNS = Cooldowns()


def provider_order(settings) -> list[str]:
    """The primary provider followed by the fallbacks, without repeats or unknown names."""
    primary = str(getattr(settings, "radar_llm_provider", "openrouter") or "openrouter").strip()
    wanted = [primary, *str(getattr(settings, "radar_llm_fallback", "") or "").split(",")]
    order: list[str] = []
    for raw in wanted:
        name = raw.strip().lower()
        if not name or name in order:
            continue
        if name not in PROVIDERS:
            logger.warning("ignoring unknown model provider %r in the fallback list", name)
            continue
        order.append(name)
    return order or ["openrouter"]


def model_for_provider(settings, name: str, role: str) -> str:
    """The model id to use for `role` when `name` is the provider that answers."""
    if name not in PROVIDERS:
        raise ValueError(f"unknown model provider {name!r}")
    if name == "gemini":
        if role not in _OPENROUTER_MODEL:
            raise ValueError(f"unknown model role {role!r}")
        return GEMINI_BULK_MODEL
    if name == "antigravity":
        # One setting for all three roles; empty means Antigravity's own default model.
        if role not in _OPENROUTER_MODEL:
            raise ValueError(f"unknown model role {role!r}")
        return str(getattr(settings, "radar_antigravity_model", "") or "")
    names = _CLAUDE_MODEL if name == "claude_code" else _OPENROUTER_MODEL
    if role not in names:
        raise ValueError(f"unknown model role {role!r}")
    return str(getattr(settings, names[role]))


def _find_claude(settings) -> str | None:
    """The Claude Code command on this computer, or None."""
    from spyglass_service.claude_jobs import find_claude

    return find_claude(settings)


def _agy_ready(settings) -> tuple[bool, str | None]:
    """Whether the Antigravity command exists and its settings pass the safety gate."""
    from spyglass_service.radar.agy_cli import ready

    return ready(settings)


def _stored_key(name: str) -> str | None:
    """A key the reader typed into the app (kept in the operating system's keyring), or None."""
    from spyglass_service.radar.assist import secrets_store

    return secrets_store.get_secret(name)


def provider_ready(settings, name: str) -> tuple[bool, str | None]:
    """Whether `name` can be tried (its key or command exists) and, if not, why in plain words."""
    if name == "claude_code":
        if _find_claude(settings) is None:
            return False, "The claude command was not found on this computer."
        return True, None
    if name == "gemini":
        if getattr(settings, "gemini_api_key", None) or _stored_key("gemini"):
            return True, None
        return False, "No Gemini key is set."
    if name == "antigravity":
        return _agy_ready(settings)
    if getattr(settings, "openrouter_api_key", None):
        return True, None
    return False, "No OpenRouter key is set."


def any_available(settings, *, cooldowns: Cooldowns | None = None) -> tuple[bool, str | None]:
    """Whether some provider in the order can be tried now; else the primary's reason."""
    book = cooldowns or COOLDOWNS
    order = provider_order(settings)
    first_reason: str | None = None
    for name in order:
        ok, why = provider_ready(settings, name)
        if ok and book.until(name) is None:
            return True, None
        first_reason = first_reason or why or book.reason(name)
    return False, first_reason or "No model provider is configured."


def status(settings, *, cooldowns: Cooldowns | None = None) -> list[dict]:
    """One row per provider for the settings page.

    Each row has name, label, position (1 for the primary, None when not in the order),
    available (can be used right now), reason (why not, else None) and cooling_down_until
    (ISO time or None). The providers in use come first, in order.
    """
    book = cooldowns or COOLDOWNS
    order = provider_order(settings)
    rows = []
    for name in [*order, *(p for p in PROVIDERS if p not in order)]:
        ready, why = provider_ready(settings, name)
        until = book.until(name)
        paused_reason = book.reason(name) if until is not None else None
        rows.append({
            "name": name, "label": _LABELS[name],
            "position": order.index(name) + 1 if name in order else None,
            "available": ready and until is None,
            "reason": paused_reason or (None if ready else why),
            "cooling_down_until": datetime.fromtimestamp(until, UTC).isoformat() if until else None,
        })
    return rows


def call_with_fallback(
    settings,
    role: str,
    messages: list[dict],
    schema: dict,
    *,
    call_one: Callable[[str], dict],
    order: list[str] | None = None,
    cooldowns: Cooldowns | None = None,
) -> dict:
    """Return the first provider's answer; move on only when a provider cannot be used.

    `call_one(name)` makes one provider's call (messages and schema are already bound into it by
    the caller; `role`, `messages` and `schema` are kept in the signature so the seam reads the
    same as before and for logging). It raises LlmUnavailable when that provider cannot be used
    and ValueError for an unusable reply, which is passed on without trying another provider.
    Raises LlmUnavailable naming every provider tried and why when none could answer.
    """
    book = cooldowns or COOLDOWNS
    providers = list(dict.fromkeys(order if order is not None else provider_order(settings)))
    # With one provider there is nothing to fall back to, and a pause would only keep the reader
    # from retrying right after fixing the problem (adding credit, signing in), so none is kept.
    remember = len(providers) > 1
    problems: list[str] = []
    for name in providers:
        until = book.until(name) if remember else None
        if until is not None:
            minutes = max(1, round((until - book.now()) / 60))
            problems.append(f"{name}: {book.reason(name)} (not retried for about {minutes} min)")
            continue
        try:
            return call_one(name)
        except LlmUnavailable as exc:
            reason = str(exc) or "unavailable"
            if remember:
                book.mark(name, reason)
            problems.append(f"{name}: {reason}")
            logger.warning("model provider %s unavailable for %s: %s", name, role, reason)
    raise LlmUnavailable("No model provider could be used. " + " ".join(problems))
