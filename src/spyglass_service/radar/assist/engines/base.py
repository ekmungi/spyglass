"""The engine contract: what every assistant engine offers and the events it streams.

An engine is anything that can turn a system prompt plus a list of chat messages into streamed
text: an HTTP API, or a command-line program the reader has installed. `stream` is a generator.
Closing it (or letting it be garbage collected) must release what it holds: the HTTP response
or, for a command-line engine, the child process and everything that process started.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Event kinds. "delta" carries text; "session" carries an id the engine wants kept for the next
# turn; "ping" means nothing arrived for a moment (it lets the caller check for cancellation);
# "usage" carries the call's token figures (a `usage_parse.Tokens`) just before "done"; "done" and
# "error" end the stream.
DELTA = "delta"
SESSION = "session"
PING = "ping"
USAGE = "usage"
DONE = "done"
ERROR = "error"

# Upper bound on the length of one assistant answer, sent with every request. Chat answers are far
# shorter, and without a limit a provider reserves the model's full maximum output (65,536 tokens
# on some models) and refuses the request when the account cannot afford that reservation.
MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class StreamEvent:
    """One step of a streamed answer: text, a session id, an idle tick, or the end."""

    kind: str
    text: str = ""
    data: object = None

    @classmethod
    def delta(cls, text: str) -> "StreamEvent":
        """A piece of the answer text."""
        return cls(DELTA, text)

    @classmethod
    def session(cls, session_id: str) -> "StreamEvent":
        """An external session id to store on the thread and pass back on the next turn."""
        return cls(SESSION, session_id)

    @classmethod
    def usage(cls, tokens: object) -> "StreamEvent":
        """The token figures of this call, reported once before the end of the stream."""
        return cls(USAGE, data=tokens)

    @classmethod
    def ping(cls) -> "StreamEvent":
        """Nothing new yet; emitted by engines that would otherwise block for long."""
        return cls(PING)

    @classmethod
    def done(cls) -> "StreamEvent":
        """The answer is complete."""
        return cls(DONE)

    @classmethod
    def error(cls, message: str) -> "StreamEvent":
        """The engine failed; `message` is short, human, and free of secrets and stack traces."""
        return cls(ERROR, message)


class EngineError(RuntimeError):
    """An engine problem whose message is already safe to show the reader."""


def http_error_message(label: str, status: int, body: str) -> str:
    """A short reader-facing sentence for a failed HTTP request to an engine.

    The provider's own message is appended when the body is JSON with an error message; it is cut
    short so a long page of HTML or a stack trace never reaches the reader.
    """
    reasons = {
        400: "rejected the request",
        401: "did not accept the API key",
        402: "says the account has no credit left",
        403: "refused access (check the key and its permissions)",
        404: "does not know that model or address",
        408: "timed out",
        429: "is rate limiting requests; try again in a moment",
    }
    reason = reasons.get(status) or ("is having trouble right now" if status >= 500 else "failed")
    detail = ""
    try:
        parsed = json.loads(body)
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or "")
        elif isinstance(err, str):
            detail = err
    except ValueError:
        detail = ""
    detail = " ".join(detail.split())[:200]
    message = f"{label} {reason} (HTTP {status})."
    return f"{message} {detail}".strip() if detail else message


@runtime_checkable
class Engine(Protocol):
    """What the registry and the thread runner need from an engine."""

    id: str
    label: str
    kind: str  # "api" (a hosted service), "local" (a server on this machine) or "cli" (a command)

    def models(self) -> list[dict]:
        """Models offered, as [{"id", "label"}]."""
        ...

    def available(self) -> tuple[bool, str | None]:
        """Whether the engine can be used now, and the plain reason when it cannot."""
        ...

    def stream(
        self,
        *,
        system: str,
        messages: list[dict],
        model: str,
        session: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream the answer to the last message in `messages`.

        `messages` are {"role": "user"|"assistant", "content": str}. `session` is the id this
        engine returned earlier on the same thread, when it keeps its own history. The stream
        ends with exactly one done or error event.
        """
        ...
