"""The steps Windows setup runs with Spyglass's own Python, after uv has built the environment.

    pythonw -I -X utf8 -m spyglass_service.desktop.setup_steps install --install-dir <folder>
    pythonw -I -X utf8 -m spyglass_service.desktop.setup_steps uninstall --install-dir <folder>

The setup package records each ticked part as a value under FEATURES_KEY, so these steps read
the user's choices from the registry. Each choice is applied only when it changed since the last
run (recorded in setup-state.json), so a later Modify for another part never undoes what the user
changed in the app itself, such as the "Start with Windows" switch. Every step is logged to
install.log beside desktop.json, and a step that fails is logged without stopping the others:
only preparing Python, which runs before these steps, can stop setup.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from spyglass_service import __version__
from spyglass_service.desktop.connector import Runner, add_connector, find_claude, remove_connector
from spyglass_service.desktop.datadir import DEFAULT_PORT, ConfigError, config_path, load_config
from spyglass_service.desktop.platform_base import no_window_flags
from spyglass_service.desktop.platform_windows import (
    LAUNCHER_NAME,
    RUN_KEY,
    RUN_VALUE,
    RegistryAdapter,
)
from spyglass_service.desktop.warm_up import warm_up_modules
from spyglass_service.desktop.ytengine import install_engine, remove_engine

# Where the setup package's feature components write one value per ticked part.
FEATURES_KEY = r"Software\ekmungi\Spyglass\Features"
# The browsers setup offers a guide for, as the platform adapter names them.
BROWSER_IDS = ("chrome", "edge", "brave", "vivaldi", "opera")
# Beside desktop.json: what setup applied and added, the pending browser guide, and the log.
STATE_FILE = "setup-state.json"
GUIDE_FILE = "setup-guide.json"
LOG_FILE = "install.log"
# The scheduled task an old start-up script registered; it would start a second Spyglass.
OLD_TASK_NAME = "Spyglass"
# How long one outside command (Claude Code, uv, schtasks) may take; uv downloads the engine.
COMMAND_TIMEOUT_S = 600

# A step returns what to log and the setup-state entries it changed.
StepResult = tuple[str, dict]


@dataclass(frozen=True)
class Choices:
    """The parts the user ticked in setup."""

    autostart: bool
    connector: bool
    youtube: bool
    browsers: tuple[str, ...]


@dataclass(frozen=True)
class SetupContext:
    """Everything the steps touch; tests pass fakes for the registry, the runner and the folders."""

    install_dir: Path
    registry: RegistryAdapter
    run: Runner
    config_dir: Path
    home: Path
    which: Callable[[str], str | None] = shutil.which
    warm_up: Callable[[], str] = warm_up_modules
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    settings_file: Path | None = None

    @property
    def desktop_json(self) -> Path:
        """desktop.json: the named file, or the one in the config folder."""
        return self.settings_file or self.config_dir / "desktop.json"


def log_line(config_dir: Path, text: str) -> None:
    """Append one line to install.log, creating its folder; a log that cannot be written is skipped."""
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        with open(config_dir / LOG_FILE, "a", encoding="utf-8") as log:
            log.write(text.rstrip() + "\n")
    except OSError:
        pass


def read_choices(registry: RegistryAdapter) -> Choices:
    """The ticked parts, from the values the setup package's components wrote."""
    def ticked(name: str) -> bool:
        return registry.get(FEATURES_KEY, name) == "1"

    return Choices(autostart=ticked("autostart"), connector=ticked("connector"),
                   youtube=ticked("youtube"),
                   browsers=tuple(b for b in BROWSER_IDS if ticked(f"browser.{b}")))


def _read_json(path: Path) -> dict:
    """A JSON object from `path`, or {} when it is missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    """Write `data` as UTF-8 JSON, creating the folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _port(ctx: SetupContext) -> int:
    """The port in desktop.json, or the default when there is none."""
    port = _read_json(ctx.desktop_json).get("port")
    return port if isinstance(port, int) and not isinstance(port, bool) else DEFAULT_PORT


def _points_into(command: str, folder: Path) -> bool:
    """Whether a start-up command starts a program inside `folder`."""
    return str(folder).rstrip("\\/").lower() + "\\" in command.lower().replace("/", "\\")


def _ensure_desktop_config(ctx: SetupContext) -> StepResult:
    """Write desktop.json naming no data folder, so the first start asks; keep a usable one.

    One the app cannot read is moved to desktop.json.bad and written again, because the app's
    message for it says to run setup again.
    """
    note = ""
    if ctx.desktop_json.exists():
        try:
            load_config(ctx.desktop_json)
            return f"kept {ctx.desktop_json}", {}
        except ConfigError as exc:
            os.replace(ctx.desktop_json, ctx.desktop_json.with_name(ctx.desktop_json.name + ".bad"))
            note = f"set aside an unusable {ctx.desktop_json.name} ({exc}); "
    _write_json(ctx.desktop_json, {"data_dir": None, "vault_path": None, "port": DEFAULT_PORT})
    return f"{note}wrote {ctx.desktop_json}; the first start asks for the data folder", {}


def _remove_old_task(ctx: SetupContext) -> StepResult:
    """Delete the scheduled task an old start-up script registered, when it exists."""
    schtasks = str(Path(ctx.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "schtasks.exe")
    if ctx.run([schtasks, "/Query", "/TN", OLD_TASK_NAME], None)[0] != 0:
        return "none found", {}
    code, _ = ctx.run([schtasks, "/Delete", "/TN", OLD_TASK_NAME, "/F"], None)
    return ("removed" if code == 0 else f"could not remove it (exit code {code})"), {}


def _apply_autostart(ctx: SetupContext, choices: Choices, state: dict) -> StepResult:
    """Write or remove the start-up entry, the same one the app's own switch writes."""
    if state.get("autostart") == choices.autostart:
        return "unchanged; the app's own switch decides", {}
    if choices.autostart:
        ctx.registry.set(RUN_KEY, RUN_VALUE, f'"{ctx.install_dir / LAUNCHER_NAME}" --background')
        return "on", {"autostart": True}
    current = ctx.registry.get(RUN_KEY, RUN_VALUE)
    if current is not None and _points_into(current, ctx.install_dir):
        ctx.registry.delete(RUN_KEY, RUN_VALUE)
        return "off; removed this install's entry", {"autostart": False}
    return "off", {"autostart": False}


_CONNECTOR_NOTES = {
    "added": "added the spyglass connector to Claude Code",
    "present": "Claude Code already has this Spyglass's connector",
    "foreign": "Claude Code has a connector named spyglass that points elsewhere; it was left as it is",
    "no-claude": "Claude Code was not found; nothing was changed",
    "failed": "Claude Code refused the change; the details are above",
    "removed": "removed the connector setup had added",
    "absent": "the connector setup had added is already gone",
}


def _apply_connector(ctx: SetupContext, choices: Choices, state: dict) -> StepResult:
    """Add the Claude Code connector, or remove it if setup added it."""
    if state.get("connector") == choices.connector:
        return "unchanged", {}
    claude = find_claude(ctx.home, which=ctx.which)
    port = _port(ctx)
    if choices.connector:
        status = add_connector(claude, port, home=ctx.home, run=ctx.run)
        added = bool(state.get("connector_added")) or status == "added"
        return _CONNECTOR_NOTES[status], {"connector": True, "connector_added": added}
    if not state.get("connector_added"):
        return "setup had not added a connector", {"connector": False}
    status = remove_connector(claude, port, home=ctx.home, run=ctx.run)
    still_ours = status in ("failed", "no-claude")
    return _CONNECTOR_NOTES[status], {"connector": False, "connector_added": still_ours}


def _apply_youtube(ctx: SetupContext, choices: Choices, state: dict) -> StepResult:
    """Install the yt-transcribe engine, or remove it if setup installed it."""
    if state.get("youtube") == choices.youtube:
        return "unchanged", {}
    uv = ctx.install_dir / "uv.exe"
    if choices.youtube:
        status = install_engine(uv, home=ctx.home, which=ctx.which, run=ctx.run,
                                environ=ctx.environ)
        installed = bool(state.get("youtube_installed")) or status == "installed"
        return f"engine {status}", {"youtube": True, "youtube_installed": installed}
    if not state.get("youtube_installed"):
        return "setup had not installed the engine", {"youtube": False}
    status = remove_engine(uv, run=ctx.run, environ=ctx.environ)
    return f"engine {status}", {"youtube": False, "youtube_installed": status != "removed"}


def _apply_browsers(ctx: SetupContext, choices: Choices, state: dict) -> StepResult:
    """Ask the app to show the extension guide for each newly ticked browser, once."""
    guided = set(state.get("browsers_guided") or [])
    new = [b for b in choices.browsers if b not in guided]
    if not new:
        return "no new browsers", {"browsers_guided": list(choices.browsers)}
    guide = ctx.config_dir / GUIDE_FILE
    pending = [b for b in _read_json(guide).get("browsers", []) if b in BROWSER_IDS]
    _write_json(guide, {"browsers": pending + [b for b in new if b not in pending]})
    return f"Spyglass shows the extension guide for {', '.join(new)}", {
        "browsers_guided": list(choices.browsers)}


def _run_steps(ctx: SetupContext, steps: list[tuple[str, Callable[[], StepResult]]],
               state: dict) -> dict:
    """Run each step, logging its result or its failure; return the state with its changes."""
    for name, step in steps:
        try:
            note, changes = step()
            state = {**state, **changes}
            log_line(ctx.config_dir, f"{name}: {note}")
        except Exception as exc:  # noqa: BLE001 -- a failed step must not stop the others
            log_line(ctx.config_dir, f"{name}: failed: {type(exc).__name__}: {exc}")
    return state


def install(ctx: SetupContext) -> int:
    """Apply the user's choices after an install, an upgrade or a Modify. Always returns 0."""
    log_line(ctx.config_dir, f"--- Spyglass {__version__} setup steps, {datetime.now():%Y-%m-%d %H:%M:%S} ---")
    choices = read_choices(ctx.registry)
    state = _read_json(ctx.config_dir / STATE_FILE)
    steps = [
        ("Settings file", lambda: _ensure_desktop_config(ctx)),
        ("Old scheduled task", lambda: _remove_old_task(ctx)),
        ("Start with Windows", lambda: _apply_autostart(ctx, choices, state)),
        ("Claude Code connector", lambda: _apply_connector(ctx, choices, state)),
        ("YouTube transcripts", lambda: _apply_youtube(ctx, choices, state)),
        ("Browser extension guide", lambda: _apply_browsers(ctx, choices, state)),
        ("First-start warm-up", lambda: (ctx.warm_up(), {})),
    ]
    # Each step reads the state as it was at the start; their changes are merged afterwards.
    final = _run_steps(ctx, steps, state)
    try:
        _write_json(ctx.config_dir / STATE_FILE, final)
    except OSError as exc:
        log_line(ctx.config_dir, f"Could not save {STATE_FILE}: {exc}")
    log_line(ctx.config_dir, "Spyglass is ready.")
    return 0


def _uninstall_autostart(ctx: SetupContext) -> StepResult:
    """Remove the start-up entry when it starts this install."""
    current = ctx.registry.get(RUN_KEY, RUN_VALUE)
    if current is not None and _points_into(current, ctx.install_dir):
        ctx.registry.delete(RUN_KEY, RUN_VALUE)
        return "removed", {}
    return "no entry of this install", {}


def _forget_setup(ctx: SetupContext) -> StepResult:
    """Delete setup's own records; desktop.json and the data folder stay."""
    for name in (STATE_FILE, GUIDE_FILE):
        (ctx.config_dir / name).unlink(missing_ok=True)
    return f"kept {ctx.desktop_json} and the data folder", {}


def uninstall(ctx: SetupContext) -> int:
    """Undo what setup added: start-up entry, connector, engine. Always returns 0."""
    log_line(ctx.config_dir, f"--- Spyglass {__version__} uninstall steps, {datetime.now():%Y-%m-%d %H:%M:%S} ---")
    state = _read_json(ctx.config_dir / STATE_FILE)
    nothing = Choices(autostart=False, connector=False, youtube=False, browsers=())
    # An unticked choice against the recorded state removes exactly what setup added.
    removal = {**state, "connector": True, "youtube": True}
    _run_steps(ctx, [
        ("Start with Windows", lambda: _uninstall_autostart(ctx)),
        ("Claude Code connector", lambda: _apply_connector(ctx, nothing, removal)),
        ("YouTube transcripts", lambda: _apply_youtube(ctx, nothing, removal)),
        ("Setup records", lambda: _forget_setup(ctx)),
    ], state)
    return 0


def make_runner(config_dir: Path) -> Runner:
    """The real command runner: no console window, output appended to install.log."""
    def run(args: list[str], env: dict | None = None) -> tuple[int, str]:
        log_line(config_dir, "> " + subprocess.list2cmdline(args))
        try:
            done = subprocess.run(  # noqa: S603 -- a fixed program and arguments, no shell
                args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=COMMAND_TIMEOUT_S, env=env, stdin=subprocess.DEVNULL,
                creationflags=no_window_flags(), check=False)
        except subprocess.TimeoutExpired:
            log_line(config_dir, f"Stopped after {COMMAND_TIMEOUT_S} s.")
            return -2, ""
        except OSError as exc:
            log_line(config_dir, f"Could not start it: {exc}")
            return -1, str(exc)
        output = (done.stdout or "") + (done.stderr or "")
        if output.strip():
            log_line(config_dir, output)
        log_line(config_dir, f"Exit code {done.returncode}.")
        return done.returncode, output

    return run


def build_context(install_dir: Path) -> SetupContext:
    """The context for this machine: the real registry, runner and folders."""
    from spyglass_service.desktop.platform_windows import _WinregRegistry

    settings_file = config_path()
    return SetupContext(install_dir=install_dir, registry=_WinregRegistry(),
                        run=make_runner(settings_file.parent), config_dir=settings_file.parent,
                        home=Path.home(), settings_file=settings_file)


COMMANDS: dict[str, Callable[[SetupContext], int]] = {"install": install, "uninstall": uninstall}


def main(argv: list[str] | None = None,
         context_factory: Callable[[Path], SetupContext] = build_context,
         commands: Mapping[str, Callable] | None = None) -> int:
    """Parse `install|uninstall --install-dir PATH` and run that command."""
    parser = argparse.ArgumentParser(prog="spyglass-setup-steps")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--install-dir", required=True, help="the folder Spyglass is installed in")
    args = parser.parse_args(argv)
    return (commands or COMMANDS)[args.command](context_factory(Path(args.install_dir)))


if __name__ == "__main__":
    sys.exit(main())
