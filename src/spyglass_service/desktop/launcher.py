"""The desktop launcher's testable core: environment, health probe, start decision, logs, lock.

The tray, the service thread and the browser (which need Windows) are added on top of these
pieces; everything here runs and is tested without a tray or a real service on port 7777.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from spyglass_service.config import Settings, apply_overlay
from spyglass_service.desktop.datadir import DesktopConfig
from spyglass_service.radar.cycle_lock import CycleFileLock

# The reading browser the desktop app asks for: Edge ships with Windows, so it is always there.
BROWSER_CHANNEL = "msedge"
# A service log over this size is moved aside at start, so logs never grow without limit.
LOG_LIMIT_BYTES = 10_000_000
NOT_SPYGLASS = "not-spyglass"


@dataclass(frozen=True)
class Health:
    """What a running Spyglass reports about itself on /api/health."""

    version: str
    started_by: str | None  # "desktop", "developer", or None for 0.40.0 and older


HealthResult = Health | Literal["not-spyglass"] | None


class StartAction(Enum):
    """What the launcher does after looking at the lock and at the port."""

    START = "start"
    OPEN_PEER = "open_peer"
    REFUSE_OTHER_SPYGLASS = "refuse_other_spyglass"
    REFUSE_PORT_BUSY = "refuse_port_busy"


def prepare_environment(config: DesktopConfig,
                        environ: MutableMapping[str, str] = os.environ) -> Settings:
    """Point the process at the installed data folder and return the settings to run with.

    Sets the SPYGLASS_* variables (so child processes see them too), moves the working
    directory into the data folder (so a stray `.env` elsewhere is never read), and layers the
    folder's settings.json over them. The values are also passed to Settings directly, so the
    result does not depend on which mapping `environ` is.
    """
    environ["SPYGLASS_DATA_DIR"] = str(config.data_dir)
    environ["SPYGLASS_PORT"] = str(config.port)
    environ["SPYGLASS_BROWSER_CHANNEL"] = BROWSER_CHANNEL
    explicit: dict = {"data_dir": config.data_dir, "port": config.port,
                      "browser_channel": BROWSER_CHANNEL}
    if config.vault_path is not None:
        environ["SPYGLASS_VAULT_PATH"] = str(config.vault_path)
        explicit["vault_path"] = config.vault_path
    os.chdir(config.data_dir)
    return apply_overlay(Settings(**explicit))


def probe_health(port: int, timeout: float = 1.0) -> HealthResult:
    """Ask whatever listens on 127.0.0.1:`port` who it is.

    Returns a Health for a JSON answer that names a version, "not-spyglass" for any other
    HTTP answer, and None when nothing answers (connection refused or timed out).
    """
    # An empty proxy map: a system proxy must never sit between us and this computer.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError:
        return NOT_SPYGLASS  # it answered HTTP, but with an error status
    except (urllib.error.URLError, OSError):
        return None  # refused or timed out: nothing is listening
    try:
        body = json.loads(raw)
    except ValueError:
        return NOT_SPYGLASS
    version = body.get("version") if isinstance(body, dict) else None
    if not isinstance(version, str):
        return NOT_SPYGLASS
    started_by = body.get("started_by")
    return Health(version, started_by if isinstance(started_by, str) else None)


def decide_start(lock_acquired: bool, health: HealthResult) -> StartAction:
    """The start decision table. Pure: waiting for a peer to come up is the caller's job.

    Without the lock, another launcher on this data folder is running or starting, so the
    right move is to open its interface whatever the port answers right now. With the lock,
    anything already answering on the port is not ours to use.
    """
    if not lock_acquired:
        return StartAction.OPEN_PEER
    if health is None:
        return StartAction.START
    if health == NOT_SPYGLASS:
        return StartAction.REFUSE_PORT_BUSY
    return StartAction.REFUSE_OTHER_SPYGLASS


def refusal_message(health: Health, port: int) -> str:
    """The text shown when `decide_start` returned REFUSE_OTHER_SPYGLASS."""
    if health.started_by == "desktop":
        return (f"Another Spyglass (version {health.version}) is already running on port "
                f"{port} with a different data folder. Quit it from its tray icon, then "
                "open Spyglass again.")
    return (f"Spyglass is already running outside the app (version {health.version}), started "
            "from a command line, a script or the Obsidian plugin's Open dashboard. Stop it, "
            "then open Spyglass again.")


def redirect_output(data_dir: Path, limit_bytes: int = LOG_LIMIT_BYTES) -> None:
    """Send stdout and stderr to service.log and service.err.log in the data folder.

    The windowed app has no console (sys.stdout may be None), so without this every message
    and traceback would be lost. A log already over `limit_bytes` is first moved to `.1`,
    replacing the previous one; the new run then appends.
    """
    streams = []
    for name in ("service.log", "service.err.log"):
        path = data_dir / name
        if path.exists() and path.stat().st_size > limit_bytes:
            os.replace(path, data_dir / f"{name}.1")
        streams.append(open(path, "a", encoding="utf-8", errors="replace", buffering=1))
    sys.stdout, sys.stderr = streams


def single_instance_lock(data_dir: Path) -> CycleFileLock:
    """The lock that lets one launcher run per data folder.

    max_age=None: the lock is held for as long as the app stays open, which can be weeks, so
    only a dead holder process may make it stale.
    """
    return CycleFileLock(data_dir / "desktop.lock", max_age=None)
