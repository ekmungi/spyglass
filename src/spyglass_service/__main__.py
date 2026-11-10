"""Entry point: `python -m spyglass_service` runs the dashboard service."""

from pathlib import Path

import uvicorn

from spyglass_service.app import create_app
from spyglass_service.config import Settings

# Built frontend relative to the repo layout; missing dir falls back to a placeholder page.
_SPA_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# How long a stop waits for open connections. Claude sessions keep their MCP stream open, so
# without a limit a stop would wait for every linked Claude window to close.
STOP_WAIT_S = 5


def main() -> None:
    """Load settings, build the app, and serve it on the configured binding. POST /api/shutdown
    stops this process."""
    settings = Settings()
    server: uvicorn.Server | None = None

    def request_stop() -> None:
        if server is not None:
            server.should_exit = True

    app = create_app(settings, spa_dir=_SPA_DIST, shutdown_handler=request_stop)
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info",
                            timeout_graceful_shutdown=STOP_WAIT_S)
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
