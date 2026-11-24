"""The yt-transcribe engine, which Windows setup installs when "YouTube transcripts" is ticked.

The engine is a separate command-line program that reads YouTube's own captions. Setup installs
it with the uv that ships with Spyglass, as a uv tool in the user's own tool folder, from the
engine's public source archive (so git is not needed). An engine that is already installed is
left alone, and setup removes only an engine it installed itself.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from spyglass_service.desktop.connector import Runner
from spyglass_service.yt_discovery import discover_yt_transcribe

# The engine's package name, which `uv tool uninstall` takes.
ENGINE_PACKAGE = "yt-transcribe"
# The engine's commit setup installs (its version 0.14.0, 11 October 2026). Pinned, so every
# install gets code that was reviewed for this release and not whatever the branch holds that day;
# move it forward deliberately with a Spyglass release.
ENGINE_COMMIT = "ebc0ed330f281a21edc3c8f8a41add051f786526"
# Where uv fetches it: that commit's archive, whose server folder holds the package.
ENGINE_SOURCE = (f"{ENGINE_PACKAGE} @ https://github.com/ekmungi/youtube-transcribe/archive/"
                 f"{ENGINE_COMMIT}.zip#subdirectory=server")


def _tool_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment for uv without the UV_ settings setup uses for Spyglass's own Python.

    With them, uv would put the tool into Spyglass's environment or its Python folder, which an
    uninstall of Spyglass deletes.
    """
    return {key: value for key, value in environ.items() if not key.upper().startswith("UV_")}


def install_engine(uv: Path, *, home: Path, which: Callable[[str], str | None] = shutil.which,
                   run: Runner, environ: Mapping[str, str]) -> str:
    """Install the engine unless one is found. Returns installed, present or failed."""
    if discover_yt_transcribe(None, home=home, which=which) is not None:
        return "present"
    code, _output = run([str(uv), "tool", "install", ENGINE_SOURCE], _tool_environment(environ))
    return "installed" if code == 0 else "failed"


def remove_engine(uv: Path, *, run: Runner, environ: Mapping[str, str]) -> str:
    """Remove the engine setup installed. Returns removed or failed."""
    code, _output = run([str(uv), "tool", "uninstall", ENGINE_PACKAGE], _tool_environment(environ))
    return "removed" if code == 0 else "failed"
