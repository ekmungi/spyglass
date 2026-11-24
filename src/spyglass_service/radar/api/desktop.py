"""Desktop API: the Settings page's "Start with Windows" switch and its browser extensions button.

GET  /desktop/autostart         whether the switch is offered, and whether it is on
PUT  /desktop/autostart         turn start-at-sign-in on or off
GET  /desktop/capabilities      which optional parts setup installed, and how to add the rest
GET  /desktop/extension         the folder with this install's copy of the browser extension
GET  /desktop/browsers         the installed browsers that have an extensions page
POST /desktop/open-extensions   open one browser's extensions page

These routes change the user's machine (a sign-in entry, a browser window), so every one is
same-origin only: a web page the reader happens to have open must not be able to call them.
The switch is offered only to the desktop app; a developer run (`python -m spyglass_service`)
must not write a sign-in entry that would start an installed copy.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from spyglass_service import capabilities
from spyglass_service.desktop.platform_base import DesktopPlatform
from spyglass_service.extension_copy import COPY_DIR
from spyglass_service.radar.api.importer import same_origin_only
from spyglass_service.request_guards import require_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/desktop", dependencies=[Depends(same_origin_only)])


class AutostartBody(BaseModel):
    """JSON body of PUT /desktop/autostart."""

    enabled: bool


class OpenExtensionsBody(BaseModel):
    """JSON body of POST /desktop/open-extensions."""

    browser: str


def _platform(request: Request) -> DesktopPlatform | None:
    """The desktop platform the app was built with, or None when there is none."""
    return getattr(request.app.state, "desktop_platform", None)


def _autostart_platform(request: Request) -> DesktopPlatform | None:
    """The platform, only when this process is the desktop app; otherwise None."""
    if getattr(request.app.state, "started_by", "developer") != "desktop":
        return None
    return _platform(request)


def _autostart_state(platform: DesktopPlatform | None) -> dict[str, bool]:
    """The reply shape shared by the GET and the PUT.

    When Windows refuses to read the start-up setting (a policy can lock the Run key), the
    switch is reported as unavailable instead of failing the whole Settings page.
    """
    if platform is None:
        return {"available": False, "enabled": False}
    try:
        return {"available": True, "enabled": platform.autostart_enabled()}
    except OSError:
        logger.warning("could not read the start-up setting", exc_info=True)
        return {"available": False, "enabled": False}


@router.get("/autostart")
def get_autostart(request: Request) -> dict[str, bool]:
    """Whether "Start with Windows" is offered here, and whether it is currently on."""
    return _autostart_state(_autostart_platform(request))


@router.put("/autostart", dependencies=[Depends(require_json)])
def put_autostart(body: AutostartBody, request: Request) -> dict[str, bool]:
    """Turn start-at-sign-in on or off; 409 when this run does not offer it."""
    platform = _autostart_platform(request)
    if platform is None:
        raise HTTPException(status_code=409, detail="start with Windows is not available here")
    try:
        platform.set_autostart(body.enabled)
    except OSError:
        logger.warning("could not write the start-up setting", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Windows refused access to the start-up setting."
        ) from None
    return _autostart_state(platform)


@router.get("/capabilities")
def get_capabilities() -> dict:
    """Which optional parts are installed (PDF reading, local AI model), and how to add the rest."""
    return capabilities.report()


@router.get("/extension")
def get_extension_folder(request: Request) -> dict[str, str]:
    """The folder holding this install's copy of the browser extension, for "Load unpacked"."""
    return {"folder": str(Path(request.app.state.settings.data_dir) / COPY_DIR)}


@router.get("/browsers")
def get_browsers(request: Request) -> list[dict[str, str]]:
    """The installed browsers as id and name; empty when there is no platform."""
    platform = _platform(request)
    if platform is None:
        return []
    return [{"id": b.id, "name": b.name} for b in platform.installed_browsers()]


@router.post("/open-extensions", status_code=204, dependencies=[Depends(require_json)])
def open_extensions(body: OpenExtensionsBody, request: Request) -> Response:
    """Open a browser's extensions page; 404 for an unknown or a known-but-uninstalled browser
    (the platform raises KeyError for both)."""
    platform = _platform(request)
    if platform is None:
        raise HTTPException(status_code=404, detail="no such browser")
    try:
        platform.open_extensions_page(body.browser)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such browser") from None
    return Response(status_code=204)
