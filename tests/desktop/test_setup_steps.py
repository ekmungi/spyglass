"""The steps Windows setup runs with Spyglass's own Python once uv has built the environment.

Every test uses a fake registry and a fake command runner, so nothing here writes the real
start-up entry, runs Claude Code or installs a tool.
"""

import json
from pathlib import Path

import pytest

from spyglass_service.desktop import setup_steps
from spyglass_service.desktop.platform_windows import RUN_KEY, RUN_VALUE
from spyglass_service.desktop.setup_steps import FEATURES_KEY, SetupContext, install, uninstall


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get(self, key: str, name: str) -> str | None:
        return self.values.get((key, name))

    def set(self, key: str, name: str, value: str) -> None:
        self.values[(key, name)] = value

    def delete(self, key: str, name: str) -> None:
        self.values.pop((key, name), None)


class FakeRun:
    """Records commands; `codes` maps a command's second word (mcp, tool, /Query) to its exit code."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.codes = codes or {}

    def __call__(self, args: list[str], env: dict | None = None) -> tuple[int, str]:
        self.calls.append(list(args))
        return self.codes.get(args[1] if len(args) > 1 else "", 0), ""

    def ran(self, word: str) -> list[list[str]]:
        return [call for call in self.calls if word in call]


@pytest.fixture()
def ctx(tmp_path: Path) -> SetupContext:
    install_dir = tmp_path / "Programs" / "Spyglass"
    install_dir.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    return SetupContext(install_dir=install_dir, registry=FakeRegistry(), run=FakeRun(),
                        config_dir=tmp_path / "config", home=home,
                        which=lambda name: "claude.exe" if name == "claude" else None,
                        warm_up=lambda: "warmed")


def _tick(ctx: SetupContext, *features: str) -> None:
    """Set the feature values the MSI's components write, clearing the rest."""
    for name in ("autostart", "connector", "youtube", "browser.chrome", "browser.edge"):
        ctx.registry.delete(FEATURES_KEY, name)
    for name in features:
        ctx.registry.set(FEATURES_KEY, name, "1")


def _launcher_entry(ctx: SetupContext) -> str:
    return f'"{ctx.install_dir / "Spyglass.exe"}" --background'


def test_first_install_writes_a_settings_file_that_names_no_data_folder(ctx: SetupContext) -> None:
    assert install(ctx) == 0
    saved = json.loads((ctx.config_dir / "desktop.json").read_text(encoding="utf-8"))
    assert saved == {"data_dir": None, "vault_path": None, "port": 7777}


def test_an_existing_settings_file_is_kept(ctx: SetupContext) -> None:
    ctx.config_dir.mkdir()
    existing = '{"data_dir": "D:\\\\Spyglass", "vault_path": null, "port": 7790}'
    (ctx.config_dir / "desktop.json").write_text(existing, encoding="utf-8")
    install(ctx)
    assert (ctx.config_dir / "desktop.json").read_text(encoding="utf-8") == existing


def test_a_broken_settings_file_is_set_aside_and_written_again(ctx: SetupContext) -> None:
    """The app tells the user to run setup again when desktop.json is unusable; that must work."""
    ctx.config_dir.mkdir()
    (ctx.config_dir / "desktop.json").write_text("{not json", encoding="utf-8")
    install(ctx)
    assert json.loads((ctx.config_dir / "desktop.json").read_text(encoding="utf-8"))["data_dir"] is None
    assert (ctx.config_dir / "desktop.json.bad").read_text(encoding="utf-8") == "{not json"


def test_start_with_windows_writes_the_launcher_entry(ctx: SetupContext) -> None:
    _tick(ctx, "autostart")
    install(ctx)
    assert ctx.registry.get(RUN_KEY, RUN_VALUE) == _launcher_entry(ctx)


def test_unticked_start_with_windows_removes_only_this_installs_entry(ctx: SetupContext) -> None:
    ctx.registry.set(RUN_KEY, RUN_VALUE, _launcher_entry(ctx))
    install(ctx)
    assert ctx.registry.get(RUN_KEY, RUN_VALUE) is None


def test_a_foreign_start_up_entry_is_kept(ctx: SetupContext) -> None:
    ctx.registry.set(RUN_KEY, RUN_VALUE, r'"D:\dev\spyglass\.venv\Scripts\pythonw.exe" -m x')
    install(ctx)
    assert ctx.registry.get(RUN_KEY, RUN_VALUE) is not None


def test_a_later_run_with_the_same_choice_keeps_the_apps_own_switch(ctx: SetupContext) -> None:
    """Modify for another part must not undo "Start with Windows" switched on in the app."""
    install(ctx)
    ctx.registry.set(RUN_KEY, RUN_VALUE, _launcher_entry(ctx))  # the app's own switch
    install(ctx)
    assert ctx.registry.get(RUN_KEY, RUN_VALUE) == _launcher_entry(ctx)


def test_the_connector_is_added_and_later_removed_when_unticked(ctx: SetupContext) -> None:
    _tick(ctx, "connector")
    install(ctx)
    assert ctx.run.ran("add")
    (ctx.home / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"spyglass": {"url": "http://127.0.0.1:7777/mcp/"}}}), encoding="utf-8")
    _tick(ctx)
    install(ctx)
    assert ctx.run.ran("remove")


def test_a_connector_setup_did_not_add_is_never_removed(ctx: SetupContext) -> None:
    (ctx.home / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"spyglass": {"url": "http://127.0.0.1:7777/mcp/"}}}), encoding="utf-8")
    _tick(ctx, "connector")
    install(ctx)
    _tick(ctx)
    install(ctx)
    uninstall(ctx)
    assert not ctx.run.ran("remove")


def test_the_engine_is_installed_and_removed_only_when_setup_added_it(ctx: SetupContext) -> None:
    _tick(ctx, "youtube")
    install(ctx)
    assert ctx.run.ran("install")
    _tick(ctx)
    install(ctx)
    assert ctx.run.ran("uninstall")


def test_the_browser_guide_lists_newly_ticked_browsers_once(ctx: SetupContext) -> None:
    guide = ctx.config_dir / "setup-guide.json"
    _tick(ctx, "browser.chrome", "browser.edge")
    install(ctx)
    assert json.loads(guide.read_text(encoding="utf-8")) == {"browsers": ["chrome", "edge"]}
    guide.unlink()  # the reader dismissed the guide
    install(ctx)
    assert not guide.exists()


def test_the_old_scheduled_task_is_removed(ctx: SetupContext) -> None:
    install(ctx)
    deletes = ctx.run.ran("/Delete")
    assert deletes and deletes[0][-3:] == ["/TN", "Spyglass", "/F"]


def test_no_scheduled_task_means_nothing_to_delete(ctx: SetupContext) -> None:
    ctx.run.codes["/Query"] = 1
    install(ctx)
    assert not ctx.run.ran("/Delete")


def test_install_runs_the_warm_up_and_logs_each_step(ctx: SetupContext) -> None:
    install(ctx)
    log = (ctx.config_dir / "install.log").read_text(encoding="utf-8")
    assert "warmed" in log
    assert "Start with Windows" in log


def test_a_failing_step_is_logged_and_the_rest_still_run(ctx: SetupContext) -> None:
    def broken() -> str:
        raise OSError("disk full")

    ctx = SetupContext(**{**ctx.__dict__, "warm_up": broken})
    _tick(ctx, "autostart")
    assert install(ctx) == 0
    assert ctx.registry.get(RUN_KEY, RUN_VALUE) == _launcher_entry(ctx)
    assert "disk full" in (ctx.config_dir / "install.log").read_text(encoding="utf-8")


def test_uninstall_removes_what_setup_added_and_keeps_the_settings(ctx: SetupContext) -> None:
    _tick(ctx, "autostart", "connector", "youtube", "browser.chrome")
    install(ctx)
    (ctx.home / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"spyglass": {"url": "http://127.0.0.1:7777/mcp/"}}}), encoding="utf-8")
    assert uninstall(ctx) == 0
    assert ctx.registry.get(RUN_KEY, RUN_VALUE) is None
    assert ctx.run.ran("remove") and ctx.run.ran("uninstall")
    assert (ctx.config_dir / "desktop.json").exists()
    assert not (ctx.config_dir / "setup-state.json").exists()
    assert not (ctx.config_dir / "setup-guide.json").exists()


def test_main_parses_the_command_and_the_install_folder(tmp_path: Path) -> None:
    seen: list[tuple[str, Path]] = []

    def factory(install_dir: Path) -> str:
        seen.append(("built", install_dir))
        return "context"

    def fake_install(context: str) -> int:
        seen.append(("install", Path(context)))
        return 0

    code = setup_steps.main(["install", "--install-dir", str(tmp_path)], context_factory=factory,
                            commands={"install": fake_install, "uninstall": fake_install})
    assert code == 0
    assert seen == [("built", tmp_path), ("install", Path("context"))]
