"""Entry point: `python -m spyglass_service` runs the dashboard service.

`build_server` is the one place the service is assembled; the tray launcher calls it too, so the
two entries cannot drift apart."""

from collections.abc import Callable
from pathlib import Path

import uvicorn

from spyglass_service.app import create_app
from spyglass_service.config import Settings
from spyglass_service.desktop.platform_base import default_platform

# Built frontend relative to the repo layout; missing dir falls back to a placeholder page.
_SPA_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# How long a stop waits for open connections. Claude sessions keep their MCP stream open, so
# without a limit a stop would wait for every linked Claude window to close. Three seconds plus
# the workers' own limits keep the whole stop inside eight seconds.
STOP_WAIT_S = 3


def build_server(
    settings: Settings,
    *,
    started_by: str = "developer",
    on_stop: Callable[[], None] | None = None,
    extra_app_kwargs: dict | None = None,
) -> uvicorn.Server:
    """Build the service and the uvicorn server that will run it; the caller runs it.

    settings: runtime configuration. started_by: who launched this process, reported by
    /api/health. on_stop: called by POST /api/shutdown after the server is told to exit.
    extra_app_kwargs: further keyword arguments for create_app (the launcher and tests use it).
    """
    server: uvicorn.Server | None = None

    def request_stop() -> None:
        if server is not None:
            server.should_exit = True
        if on_stop is not None:
            on_stop()

    # radar=True: this is the real service, so the built-in scheduler collects, judges and
    # composes on its own; nothing else needs to be open.
    app = create_app(settings, spa_dir=_SPA_DIST, shutdown_handler=request_stop, radar=True,
                     started_by=started_by, desktop_platform=default_platform(),
                     **(extra_app_kwargs or {}))
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info",
                            timeout_graceful_shutdown=STOP_WAIT_S)
    server = uvicorn.Server(config)
    return server


def main() -> None:
    """Load settings, build the server, and serve it on the configured binding. POST
    /api/shutdown stops this process."""
    build_server(Settings()).run()


if __name__ == "__main__":
    main()
