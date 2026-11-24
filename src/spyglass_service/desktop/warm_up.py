"""The first-start warm-up that setup runs: load every Spyglass and uvicorn module once.

Windows inspects a new program's files closely the first time they load, which made the first
start after an install take over 30 seconds; later starts take a few. Setup runs this with the
windowless Python that Spyglass.exe starts, so that work happens while setup still runs. It only
imports: nothing is started and no data is touched.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import time

# The packages whose modules the first start loads.
WARM_PACKAGES = ("spyglass_service", "uvicorn")


def warm_up_modules(packages: tuple[str, ...] = WARM_PACKAGES) -> str:
    """Import every module of `packages`; return a one-line summary naming any that failed."""
    started = time.perf_counter()
    failed: list[str] = []
    for name in packages:
        try:
            package = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 -- the summary reports it; setup goes on
            failed.append(f"{name}: {exc}")
            continue
        for found in pkgutil.walk_packages(getattr(package, "__path__", []), name + ".",
                                           onerror=failed.append):
            try:
                importlib.import_module(found.name)
            except Exception as exc:  # noqa: BLE001 -- as above
                failed.append(f"{found.name}: {exc}")
    seconds = time.perf_counter() - started
    return (f"Loaded {len(sys.modules)} modules in {seconds:.1f} s. "
            f"Not loaded: {', '.join(failed) if failed else 'none'}")
