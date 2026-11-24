"""The yt-transcribe engine that setup installs with the bundled uv, and removes only if it added it."""

import re
from pathlib import Path

from spyglass_service.desktop.ytengine import ENGINE_SOURCE, install_engine, remove_engine


class FakeRun:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[tuple[list[str], dict | None]] = []
        self.code = code

    def __call__(self, args: list[str], env: dict | None = None) -> tuple[int, str]:
        self.calls.append((list(args), env))
        return self.code, "output"


def test_installs_the_engine_from_its_archive_with_the_bundled_uv(tmp_path: Path) -> None:
    run = FakeRun()
    status = install_engine(tmp_path / "uv.exe", home=tmp_path, which=lambda _n: None, run=run,
                            environ={"PATH": "x", "UV_PROJECT_ENVIRONMENT": "venv"})
    assert status == "installed"
    args, env = run.calls[0]
    assert args == [str(tmp_path / "uv.exe"), "tool", "install", ENGINE_SOURCE]
    assert "github.com/ekmungi/youtube-transcribe" in ENGINE_SOURCE
    assert "#subdirectory=server" in ENGINE_SOURCE
    # Setup's own uv settings point at Spyglass's environment; the tool must not inherit them.
    assert env == {"PATH": "x"}


def test_the_engine_source_is_pinned_to_one_commit() -> None:
    """A branch archive would install whatever the branch holds on the day of the install."""
    assert re.search(r"/archive/[0-9a-f]{40}\.zip#", ENGINE_SOURCE)
    assert "refs/heads" not in ENGINE_SOURCE


def test_an_engine_that_is_already_there_is_left_alone(tmp_path: Path) -> None:
    run = FakeRun()
    status = install_engine(tmp_path / "uv.exe", home=tmp_path, which=lambda _n: "C:/yt.exe",
                            run=run, environ={})
    assert status == "present"
    assert run.calls == []


def test_a_failed_install_is_reported(tmp_path: Path) -> None:
    status = install_engine(tmp_path / "uv.exe", home=tmp_path, which=lambda _n: None,
                            run=FakeRun(code=2), environ={})
    assert status == "failed"


def test_removes_the_engine_by_its_package_name(tmp_path: Path) -> None:
    run = FakeRun()
    assert remove_engine(tmp_path / "uv.exe", run=run, environ={}) == "removed"
    assert run.calls[0][0] == [str(tmp_path / "uv.exe"), "tool", "uninstall", "yt-transcribe"]
