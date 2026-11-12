"""Radar HTTP API: one router assembled from the modules that exist.

Each feature owns one module here that exposes `router` (an APIRouter with no prefix). They are
all mounted under /api/radar. A module that is missing or fails to import is skipped and
logged, so one broken feature never takes the whole API down.
"""

import importlib
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

# Module name -> what it serves. Order only affects the generated docs.
MODULES = ("items", "briefs", "assist", "profile", "sources", "watch", "papers",
           "feed_search", "tracks", "media", "privacy", "importer", "import_direct", "bridge",
           "filing", "usage")


def build_router() -> APIRouter:
    """Build the /api/radar router from every importable feature module."""
    root = APIRouter(prefix="/api/radar")
    for name in MODULES:
        try:
            module = importlib.import_module(f"spyglass_service.radar.api.{name}")
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith(f"radar.api.{name}"):
                continue  # feature not built yet
            logger.exception("radar api module %s failed to import", name)
            continue
        except Exception:
            logger.exception("radar api module %s failed to import", name)
            continue
        root.include_router(module.router)
    return root
