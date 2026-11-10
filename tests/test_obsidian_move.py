"""Tests for moving a note through the user's Obsidian MCP server.

Spyglass makes the move itself, with the server settings Claude Code uses: an HTTP address and a
login header that may name an environment variable (`Bearer ${OBSIDIAN_API_KEY}`).
"""

import asyncio
import gc
import json
import socket
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import pytest
import uvicorn
from fastmcp import FastMCP
from fastmcp.client.transports import FastMCPTransport, SSETransport, StdioTransport, StreamableHttpTransport
from fastmcp.server.dependencies import get_http_headers

from spyglass_service import obsidian_move as om
from spyglass_service.config import Settings


def settings_with_server(tmp_path: Path, server: dict) -> Settings:
    vault = tmp_path / "Vault"
    vault.mkdir(exist_ok=True)
    (vault / ".mcp.json").write_text(json.dumps({"mcpServers": {"obsidian-vault": server}}))
    return Settings(_env_file=None, data_dir=tmp_path / "data", vault_path=vault)


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch) -> None:
    """Keep the tests away from the real ~/.claude.json."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


# --- reading the server settings -----------------------------------------------------------------


def test_environment_references_are_expanded_as_claude_code_does() -> None:
    env = {"KEY": "abc"}
    assert om.expand_env("Bearer ${KEY}", env) == "Bearer abc"
    assert om.expand_env("${NOPE:-fallback}", env) == "fallback"
    assert om.expand_env("${KEY:-fallback}", env) == "abc"
    assert om.expand_env("a $KEY and $(KEY)", env) == "a $KEY and $(KEY)"


def test_a_missing_variable_is_named_in_the_error() -> None:
    with pytest.raises(om.ObsidianMoveError, match="OBSIDIAN_API_KEY"):
        om.expand_env("Bearer ${OBSIDIAN_API_KEY}", {})


def test_an_http_server_becomes_a_streamable_http_transport() -> None:
    server = {"type": "http", "url": "http://127.0.0.1:27123/mcp/",
              "headers": {"Authorization": "Bearer ${KEY}"}}
    transport = om.transport_for(server, {"KEY": "abc"})
    assert isinstance(transport, StreamableHttpTransport)
    assert transport.url == "http://127.0.0.1:27123/mcp/"
    assert transport.headers == {"Authorization": "Bearer abc"}


def test_a_url_without_a_type_is_http_and_sse_is_kept() -> None:
    assert isinstance(om.transport_for({"url": "http://127.0.0.1:1/mcp/"}, {}),
                      StreamableHttpTransport)
    assert isinstance(om.transport_for({"type": "sse", "url": "http://127.0.0.1:1/sse"}, {}),
                      SSETransport)


def test_a_command_server_becomes_a_stdio_transport() -> None:
    server = {"command": "node", "args": ["server.js", "${PORT}"], "env": {"TOKEN": "${KEY}"}}
    transport = om.transport_for(server, {"KEY": "abc", "PORT": "27123"})
    assert isinstance(transport, StdioTransport)
    assert transport.command == "node" and transport.args == ["server.js", "27123"]
    assert transport.env == {"TOKEN": "abc"}


def test_a_server_that_is_neither_http_nor_a_command_is_refused() -> None:
    with pytest.raises(om.ObsidianMoveError, match="obsidian-vault"):
        om.transport_for({"type": "websocket"}, {}, name="obsidian-vault")


def test_the_service_uses_this_move_unless_a_test_swaps_it(tmp_path: Path) -> None:
    from spyglass_service.mcp_server import ServiceState

    state = ServiceState(settings=settings_with_server(tmp_path, {}), engine=None)
    assert state.obsidian_move is om.move_note


# --- the move ------------------------------------------------------------------------------------


def stand_in(calls: list, fail: str | None = None, delay: float = 0.0) -> FastMCP:
    """A tiny server with the Obsidian server's vault_move tool. Its overwrite default is the
    unsafe one, so a test sees False only when Spyglass sends it."""
    mcp = FastMCP("obsidian-vault")

    @mcp.tool
    async def vault_move(path: str, destination: str, allowOverwrite: bool = True) -> str:
        calls.append((path, destination, allowOverwrite))
        if delay:
            import asyncio
            await asyncio.sleep(delay)
        if fail:
            raise ValueError(fail)
        return f"Moved {path} to {destination}"

    return mcp


async def test_the_move_calls_vault_move_without_allowing_an_overwrite(
        tmp_path: Path, monkeypatch) -> None:
    calls: list = []
    settings = settings_with_server(tmp_path, {"type": "http", "url": "http://127.0.0.1:1/mcp/"})
    monkeypatch.setattr(om, "transport_for", lambda *a, **k: FastMCPTransport(stand_in(calls)))
    await om.move_note(settings, "03 RESOURCES/Spyglass/a.md", "02 AREAS/Imaging/")
    assert calls == [("03 RESOURCES/Spyglass/a.md", "02 AREAS/Imaging/", False)]


async def test_a_refusal_from_obsidian_is_reported_in_its_own_words(
        tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_server(tmp_path, {"type": "http", "url": "http://127.0.0.1:1/mcp/"})
    monkeypatch.setattr(om, "transport_for",
                        lambda *a, **k: FastMCPTransport(stand_in([], fail="Destination exists")))
    with pytest.raises(om.ObsidianMoveError, match="Destination exists"):
        await om.move_note(settings, "a.md", "b/")


async def test_an_obsidian_that_does_not_answer_in_time_is_reported(
        tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_server(tmp_path, {"type": "http", "url": "http://127.0.0.1:1/mcp/"})
    monkeypatch.setattr(om, "transport_for",
                        lambda *a, **k: FastMCPTransport(stand_in([], delay=5)))
    with pytest.raises(om.ObsidianMoveError, match="did not answer"):
        await om.move_note(settings, "a.md", "b/", timeout=0.3)


async def test_nothing_listening_is_reported_not_raised_raw(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = settings_with_server(tmp_path, {"type": "http", "url": f"http://127.0.0.1:{port}/mcp/"})
    with pytest.raises(om.ObsidianMoveError, match="could not reach"):
        await om.move_note(settings, "a.md", "b/", timeout=3)


@asynccontextmanager
async def refusing_server():
    """A bare HTTP server, in the test's own event loop, that answers every request 401, as a
    server given a wrong key does. Yields its port."""
    async def refuse(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read(65536)
            writer.write(b"HTTP/1.1 401 Unauthorized\r\ncontent-length: 0\r\n\r\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(refuse, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("key, in_url", [("SECRETKEY123", True), ("SECRETKEY123\n", False)])
async def test_an_error_never_carries_the_servers_key(
        tmp_path: Path, monkeypatch, key: str, in_url: bool) -> None:
    """The error text goes back to the run, which an article can steer, and from there to the
    job's message: a key in the address, or a header value an error echoes, must not reach it."""
    monkeypatch.setenv("OBSIDIAN_API_KEY", key)
    async with refusing_server() as port:
        query = "?key=${OBSIDIAN_API_KEY}" if in_url else ""
        server = {"type": "http", "url": f"http://127.0.0.1:{port}/mcp/{query}",
                  "headers": {"Authorization": "Bearer ${OBSIDIAN_API_KEY}"}}
        with pytest.raises(om.ObsidianMoveError) as caught:
            await om.move_note(settings_with_server(tmp_path, server), "a.md", "b/", timeout=5)
    assert "SECRETKEY123" not in str(caught.value)
    assert "could not reach" in str(caught.value)


async def test_a_missing_server_setting_is_reported(tmp_path: Path) -> None:
    settings = settings_with_server(tmp_path, {})
    (settings.vault_path / ".mcp.json").unlink()
    with pytest.raises(om.ObsidianMoveError, match="obsidian-vault"):
        await om.move_note(settings, "a.md", "b/")


@contextmanager
def serving(mcp: FastMCP):
    """Run a stand-in server over real HTTP on a free port; yield its address."""
    # ws="none": the stand-in needs no WebSockets, and uvicorn's default would import the
    # deprecated websockets.legacy module, whose warning the test settings turn into an error
    # inside the server thread, so the server would never start.
    server = uvicorn.Server(uvicorn.Config(mcp.http_app(), host="127.0.0.1", port=0,
                                           log_level="warning", ws="none"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "the stand-in server did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(10)
        # Collect the stand-in's garbage now, inside the test that made it, so the MCP library's
        # unclosed-stream warnings (see the filter on the test below) cannot land on a later test.
        gc.collect()


# The MCP library's own server (mcp 1.27) never closes the reading end of each request's event
# stream, and anyio 4.13 warns about every such stream when it is collected. That code runs only in
# the stand-in server here; Spyglass's client closes everything it opens, which a check with
# instrumented streams confirmed. The filter covers that one warning, in this one test.
@pytest.mark.filterwarnings(
    "ignore:.*MemoryObjectReceiveStream:pytest.PytestUnraisableExceptionWarning")
async def test_over_real_http_the_login_header_arrives_with_its_variable_filled_in(
        tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []
    mcp = FastMCP("obsidian-vault")

    @mcp.tool
    def vault_move(path: str, destination: str, allowOverwrite: bool = False) -> str:
        seen.append(get_http_headers(include={"authorization"}).get("authorization", ""))
        return "ok"

    monkeypatch.setenv("OBSIDIAN_API_KEY", "secret-test-key")
    with serving(mcp) as url:
        server = {"type": "http", "url": url, "headers": {"Authorization": "Bearer ${OBSIDIAN_API_KEY}"}}
        await om.move_note(settings_with_server(tmp_path, server), "a.md", "b/", timeout=10)
    assert seen == ["Bearer secret-test-key"]
