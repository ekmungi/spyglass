"""First-start API: the page a fresh install opens on, and the browser extension guide.

GET  /desktop/first-start          whether the page is needed, the folder in use, the guide's browsers
POST /desktop/first-start          save the chosen data folder and vault; restart on another folder
POST /desktop/setup-guide/dismiss  the reader finished or skipped the extension guide

Setup writes desktop.json naming no data folder, so the desktop app starts on the default folder
and this page asks where the data should live and which vault to use. A folder goes through the
same check the installer used (older or newer data is refused). Choosing another folder saves it
and restarts Spyglass on it; keeping the default needs no restart. Setup also lists the browsers
the reader ticked in setup-guide.json, and the page shows the "Load unpacked" steps for each.
Every route is same-origin only: a web page must not be able to move the data.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from spyglass_service import __version__
from spyglass_service.config import save_overlay
from spyglass_service.desktop.datadir import (
    ConfigError,
    DesktopConfig,
    FolderVerdict,
    check_data_dir,
    config_path,
    load_config,
    save_config,
)
from spyglass_service.desktop.platform_base import no_window_flags
from spyglass_service.desktop.platform_windows import launcher_path
from spyglass_service.desktop.setup_steps import GUIDE_FILE
from spyglass_service.radar.api.importer import same_origin_only
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/desktop", dependencies=[Depends(same_origin_only)])

# Longest folder path accepted; Windows' classic limit is 260 characters.
PATH_MAX = 500


class FirstStartBody(BaseModel):
    """JSON body of POST /desktop/first-start."""

    data_dir: str = Field(max_length=PATH_MAX)
    vault_path: str | None = Field(default=None, max_length=PATH_MAX)


def install_folder() -> Path | None:
    """The folder Spyglass is installed in (where Spyglass.exe is), or None for a repository run."""
    launcher = launcher_path(Path(sys.executable).with_name("pythonw.exe"))
    return launcher.parent if launcher is not None else None


def spawn_restart() -> None:
    """Start a new Spyglass that waits for this one to free the port; this one then stops."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = launcher_path(pythonw)
    # In the background: the first-start page reloads itself, so no second tab should open.
    args = ([str(launcher), "--restart", "--background"] if launcher is not None
            else [str(pythonw), "-m", "spyglass_service.desktop", "--restart", "--background"])
    flags = (no_window_flags() | getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen(args, creationflags=flags, close_fds=True,  # noqa: S603 -- no shell
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _is_desktop(request: Request) -> bool:
    """Whether this process is the desktop app (a developer run never shows these pages)."""
    return getattr(request.app.state, "started_by", "developer") == "desktop"


def _settings_file() -> DesktopConfig | None:
    """desktop.json as the launcher read it, or None when it is missing or broken."""
    try:
        return load_config(config_path())
    except ConfigError:
        return None


def _guide_browsers(request: Request) -> list[dict[str, str]]:
    """The browsers setup asked a guide for that are still installed, in the platform's order."""
    try:
        wanted = json.loads((config_path().parent / GUIDE_FILE).read_text(encoding="utf-8"))
        wanted = wanted.get("browsers") if isinstance(wanted, dict) else None
    except (OSError, ValueError):
        return []
    platform = getattr(request.app.state, "desktop_platform", None)
    if platform is None or not isinstance(wanted, list):
        return []
    return [{"id": b.id, "name": b.name} for b in platform.installed_browsers() if b.id in wanted]


def _same_folder(first: Path, second: Path) -> bool:
    """Whether two paths name the same folder, ignoring case and a trailing separator."""
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _inside(path: Path, folder: Path) -> bool:
    """Whether `path` is `folder` or lies under it."""
    inner, outer = (os.path.normcase(os.path.abspath(p)) for p in (path, folder))
    return inner == outer or inner.startswith(outer.rstrip("\\/") + os.sep)


def _refuse(message: str) -> HTTPException:
    """A 400 whose detail the page shows as it is."""
    return HTTPException(status_code=400, detail=message)


def _checked_folder(text: str) -> Path:
    """The chosen data folder, created if missing, after the usual checks; 400 with the reason."""
    text = text.strip()
    folder = Path(text)
    if not text or not folder.is_absolute():
        raise _refuse("Give the full path of a folder, such as D:\\Spyglass data.")
    program = install_folder()
    if program is not None and _inside(folder, program):
        raise _refuse(f"Choose a data folder outside the program folder {program}, so that an "
                      "upgrade or an uninstall can never touch your data.")
    verdict, message = check_data_dir(folder, __version__, must_exist=False)
    if verdict is not FolderVerdict.OK:
        raise _refuse(message)
    if folder.exists() and not folder.is_dir():
        raise _refuse(f"{folder} is a file, not a folder.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _refuse(f"Spyglass cannot create the folder {folder}: {exc.strerror or exc}") from None
    return folder


def _checked_vault(text: str | None) -> Path | None:
    """The chosen vault, which must be an existing folder, or None when none was given."""
    if text is None or not text.strip():
        return None
    vault = Path(text.strip())
    if not vault.is_absolute() or not vault.is_dir():
        raise _refuse(f"The vault folder {vault} does not exist. Choose your vault folder, or "
                      "leave it empty and set it later in Settings.")
    return vault


@router.get("/first-start")
def get_first_start(request: Request) -> dict:
    """Whether the first-start page is needed, the folder and vault in use, and the guide."""
    settings = request.app.state.settings
    config = _settings_file() if _is_desktop(request) else None
    return {
        "needed": config is not None and config.first_start,
        "data_dir": str(settings.data_dir),
        "vault_path": str(settings.vault_path) if settings.vault_path else None,
        "browsers": _guide_browsers(request) if _is_desktop(request) else [],
    }


@router.post("/first-start", dependencies=[Depends(require_json)])
def post_first_start(body: FirstStartBody, request: Request) -> dict:
    """Save the data folder and vault in desktop.json; restart Spyglass on another folder.

    409 when the folder was already chosen, 400 (with the reason) for a refused folder or vault.
    """
    config = _settings_file() if _is_desktop(request) else None
    if config is None or not config.first_start:
        raise HTTPException(status_code=409, detail="The data folder was already chosen.")
    folder = _checked_folder(body.data_dir)
    vault = _checked_vault(body.vault_path)
    save_config(DesktopConfig(data_dir=folder, vault_path=vault, port=config.port), config_path())
    settings = request.app.state.settings
    restart = not _same_folder(folder, Path(settings.data_dir))
    if not restart:
        if vault is not None:
            # As when the vault is saved in Settings: it applies now and after every start.
            save_overlay(settings, {"vault_path": str(vault)})
            settings.vault_path = vault
        return {"restart": False, "data_dir": str(folder)}
    try:
        getattr(request.app.state, "restart_spawner", spawn_restart)()
    except OSError:
        logger.exception("Could not start Spyglass again on %s", folder)
        raise HTTPException(status_code=503, detail=(
            "The folder is saved, but Spyglass could not restart itself. Quit it from its icon "
            "in the notification area and open it again.")) from None
    stop = getattr(request.app.state, "shutdown_handler", None)
    if stop is not None:
        stop()
    return {"restart": True, "data_dir": str(folder)}


@router.post("/setup-guide/dismiss", status_code=204)
def dismiss_setup_guide() -> Response:
    """Forget the browsers setup listed, once the reader has added the extension or skipped it."""
    (config_path().parent / GUIDE_FILE).unlink(missing_ok=True)
    return Response(status_code=204)
