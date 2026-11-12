"""Assistant HTTP API: engines (and their configuration), threads, and streamed answers.

Paths are relative to /api/radar. The answer to a message is a Server-Sent Events stream of
`data: {json}` frames: delta, then done or error. Idle moments send a `: ping` comment line.
API keys are accepted by PUT /engines/{id} and go to the OS keyring; no response ever contains one.
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel import Session

from spyglass_service.models import Item
from spyglass_service.radar.assist import registry, threads
from spyglass_service.radar.assist.engines.safe_args import ENGINE_ID_RE, valid_model
from spyglass_service.radar.assist.secrets_store import SecretStoreError
from spyglass_service.radar.models import AssistThread

router = APIRouter()

_Action = Literal["explain", "relevance", "colleagues", "linkedin", "blog", "projects",
                  "feed_week", "feed_themes"]
_END = object()


class EngineUpdate(BaseModel):
    """Body of PUT /engines/{id}. The key is write-only."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    api_key: str | None = Field(default=None, max_length=500, repr=False)
    base_url: str | None = Field(default=None, max_length=300)
    models: list[str | dict] | None = Field(default=None, max_length=100)
    label: str | None = Field(default=None, max_length=60)
    default_model: str | None = Field(default=None, max_length=200)


class ThreadCreate(BaseModel):
    """Body of POST /threads. No target (or `scope: "feed"`) means the conversation about the feed."""

    model_config = ConfigDict(extra="forbid")

    item_id: int | None = None
    brief_day: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    scope: Literal["feed"] | None = None
    new: bool = False

    @model_validator(mode="after")
    def _feed_scope_has_no_target(self) -> "ThreadCreate":
        """The feed conversation belongs to neither an item nor a day."""
        if self.scope == "feed" and (self.item_id is not None or self.brief_day):
            raise ValueError("A feed conversation has no item or day.")
        return self


class MessageIn(BaseModel):
    """Body of POST /threads/{id}/messages: a question, a preset action, or both."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=20_000)
    selection: str | None = Field(default=None, max_length=20_000)
    action: _Action | None = None
    engine: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=200)

    @field_validator("engine")
    @classmethod
    def _engine_is_an_id(cls, value: str | None) -> str | None:
        """An engine is named by a registry id: lowercase letters, digits, dashes, underscores."""
        if value in (None, ""):
            return None
        if not ENGINE_ID_RE.fullmatch(value):
            raise ValueError("That is not an engine id.")
        return value

    @field_validator("model")
    @classmethod
    def _model_is_a_plain_name(cls, value: str | None) -> str | None:
        """A model name is a plain token; it can reach a command line, so nothing else passes."""
        if value in (None, ""):
            return None
        if not valid_model(value):
            raise ValueError("That is not a valid model name.")
        return value

    @model_validator(mode="after")
    def _needs_something_to_ask(self) -> "MessageIn":
        """A turn needs typed text or a preset action."""
        if not self.content.strip() and not self.action:
            raise ValueError("Write a question or choose an action.")
        return self


def _db(request: Request):
    """The application's database engine."""
    return request.app.state.engine


def _transport(request: Request):
    """An optional HTTP transport for the API engines (tests use it; normally None)."""
    return getattr(request.app.state, "assist_transport", None)


@router.get("/engines")
def get_engines(request: Request) -> list[dict]:
    """Every assistant engine with availability, models and default model."""
    with Session(_db(request)) as session:
        return registry.list_engines(request.app.state.settings, session, _transport(request))


@router.put("/engines/{engine_id}")
def put_engine(engine_id: str, body: EngineUpdate, request: Request) -> dict:
    """Configure an engine; a key in the body is stored in the keyring only."""
    with Session(_db(request)) as session:
        try:
            return registry.configure_engine(
                request.app.state.settings, session, engine_id, enabled=body.enabled,
                api_key=body.api_key, base_url=body.base_url, models=body.models,
                label=body.label, default_model=body.default_model,
                transport=_transport(request))
        except registry.ConfigError as exc:
            status = (422 if isinstance(exc, registry.ForbiddenSetting)
                      else 404 if str(exc).startswith("Unknown engine") else 400)
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except SecretStoreError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/engines/{engine_id}", status_code=204)
def delete_engine(engine_id: str, request: Request) -> Response:
    """Remove a custom server entry and its stored key."""
    with Session(_db(request)) as session:
        try:
            removed = registry.remove_custom(session, engine_id)
        except SecretStoreError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No such custom engine.")
    return Response(status_code=204)


@router.post("/threads")
def post_thread(request: Request, body: ThreadCreate | None = None) -> dict:
    """Create the thread for an item, a day's brief or the whole feed, or return the latest one.

    An empty body (or `{"scope": "feed"}`) is the conversation about the feed; `{"new": true}`
    starts a fresh one.
    """
    body = body or ThreadCreate()
    db = _db(request)
    if body.item_id is not None:
        with Session(db) as session:
            if session.get(Item, body.item_id) is None:
                raise HTTPException(status_code=404, detail="No such item.")
    thread = threads.create_or_get_thread(
        db, item_id=body.item_id, brief_day=body.brief_day, new=body.new)
    return threads.thread_detail(db, thread["id"]) or {"thread": thread, "messages": []}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, request: Request) -> dict:
    """A thread with all its messages."""
    detail = threads.thread_detail(_db(request), thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No such thread.")
    return detail


def _frame(event: dict) -> str:
    """One SSE frame for an event dict; idle pings become comment lines."""
    if event.get("type") == "ping":
        return ": ping\n\n"
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _pump(events: Iterator[dict], loop: asyncio.AbstractEventLoop, out: asyncio.Queue,
          stop: threading.Event) -> None:
    """Run the (blocking) turn generator in a thread and hand its events to the event loop.

    When `stop` is set the generator is closed, which stores the partial answer and ends the
    engine's HTTP stream or child process.
    """
    try:
        for event in events:
            if stop.is_set():
                break
            loop.call_soon_threadsafe(out.put_nowait, event)
    except RuntimeError:
        pass  # the event loop is gone (server shutting down)
    finally:
        events.close()  # type: ignore[attr-defined]
        try:
            loop.call_soon_threadsafe(out.put_nowait, _END)
        except RuntimeError:
            pass


@router.post("/threads/{thread_id}/messages")
async def post_message(thread_id: int, body: MessageIn, request: Request) -> StreamingResponse:
    """Ask a question in a thread; the answer streams back as Server-Sent Events."""
    db = _db(request)
    with Session(db) as session:
        if session.get(AssistThread, thread_id) is None:
            raise HTTPException(status_code=404, detail="No such thread.")
        if body.engine and body.engine not in registry.known_engine_ids(session):
            raise HTTPException(status_code=422, detail="Unknown engine.")
    state = getattr(request.app.state, "service_state", None)
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()
    events = threads.run_turn(
        db, request.app.state.settings, thread_id, content=body.content.strip(),
        selection=body.selection, action=body.action, engine_id=body.engine, model=body.model,
        transport=_transport(request),
        index_provider=state.ensure_index if state is not None else None)
    worker = threading.Thread(target=_pump, args=(events, loop, out, stop), daemon=True)
    worker.start()

    async def body_stream() -> AsyncIterator[str]:
        """Yield frames until the turn ends; a disconnect stops the engine."""
        try:
            while True:
                event = await out.get()
                if event is _END:
                    return
                yield _frame(event)
                if event.get("type") in ("done", "error"):
                    return
        finally:
            stop.set()

    return StreamingResponse(
        body_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
