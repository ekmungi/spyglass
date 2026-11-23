"""Spyglass.exe, the launcher program the installer puts at the root of the install folder.

These tests build the real program with the C# compiler that comes with the .NET Framework 4.x
(installer/build_launcher.ps1) and run it in a throwaway folder, where a small stand-in program
plays `.venv\\Scripts\\pythonw.exe` and records how it was started. They run only on Windows with
that compiler present; nothing here installs Spyglass or touches the running one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "installer" / "build_launcher.ps1"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
TEST_VERSION = "9.8.7"
# Long enough for a cold .NET start on a busy PC; a hung launcher fails instead of blocking the run.
RUN_TIMEOUT_S = 60

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not CSC.is_file(),
    reason="needs Windows and the .NET Framework 4.x C# compiler",
)

# A console program that records the arguments it was given (its own path removed) and the folder
# it runs in, then exits with the code in STANDIN_EXIT. It stands in for the venv's pythonw.exe.
STANDIN_SOURCE = r"""
using System;
using System.IO;

class StandIn
{
    static string Rest(string line)
    {
        line = line.TrimStart();
        int end = line.StartsWith("\"") ? line.IndexOf('"', 1) + 1 : line.IndexOfAny(new[] { ' ', '\t' });
        return end <= 0 || end >= line.Length ? "" : line.Substring(end).TrimStart();
    }

    static int Main()
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        File.WriteAllText(Path.Combine(folder, "args.txt"), Rest(Environment.CommandLine) + "\n" + Environment.CurrentDirectory);
        string code = Environment.GetEnvironmentVariable("STANDIN_EXIT");
        return string.IsNullOrEmpty(code) ? 0 : int.Parse(code);
    }
}
"""


def _powershell() -> str:
    """PowerShell 7 when present (the release job's shell), else Windows PowerShell."""
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


def _run_build(out_file: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the build script for TEST_VERSION, writing the program to `out_file`."""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BUILD_SCRIPT),
         "-Version", TEST_VERSION, "-OutFile", str(out_file), *extra],
        capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False,
    )


@pytest.fixture(scope="module")
def programs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The launcher built by the build script, and the stand-in built straight with csc."""
    build = tmp_path_factory.mktemp("build")
    launcher = build / "Spyglass.exe"
    result = _run_build(launcher)
    assert result.returncode == 0, f"build failed: {result.stdout}\n{result.stderr}"
    source = build / "StandIn.cs"
    source.write_text(STANDIN_SOURCE, encoding="utf-8")
    standin = build / "standin.exe"
    compiled = subprocess.run([str(CSC), "/nologo", "/target:exe", f"/out:{standin}", str(source)],
                              capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False)
    assert compiled.returncode == 0, compiled.stdout
    return {"launcher": launcher, "standin": standin}


def _install_folder(tmp_path: Path, programs: dict[str, Path], with_python: bool = True) -> Path:
    """A throwaway install folder, with a space in its name, holding the launcher (and stand-in)."""
    folder = tmp_path / "Spy glass"
    folder.mkdir()
    shutil.copy2(programs["launcher"], folder / "Spyglass.exe")
    if with_python:
        scripts = folder / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(programs["standin"], scripts / "pythonw.exe")
    return folder


def _launch(folder: Path, args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    """Run the launcher in `folder` from another directory, with extra environment values."""
    environment = {**os.environ, **env}
    return subprocess.run([str(folder / "Spyglass.exe"), *args], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT_S, env=environment, cwd=folder.parent, check=False)


def _recorded(folder: Path) -> tuple[str, str]:
    """The stand-in's recorded arguments and working folder."""
    arguments, cwd = (folder / ".venv" / "Scripts" / "args.txt").read_text(encoding="utf-8").split("\n")
    return arguments, cwd


def test_launcher_passes_arguments_and_folder_and_exit_code(tmp_path: Path, programs: dict[str, Path]) -> None:
    """--background reaches Python unchanged, Python runs in the install folder, its code returns."""
    folder = _install_folder(tmp_path, programs)
    result = _launch(folder, ["--background"], STANDIN_EXIT="7")
    assert result.returncode == 7
    arguments, cwd = _recorded(folder)
    assert arguments == "-m spyglass_service.desktop --background"
    assert Path(cwd) == folder


def test_launcher_keeps_quoted_arguments_intact(tmp_path: Path, programs: dict[str, Path]) -> None:
    """An argument with a space and a quoted path arrives exactly as the launcher received it."""
    folder = _install_folder(tmp_path, programs)
    result = _launch(folder, ["--data", r"C:\a b\c"])
    assert result.returncode == 0
    arguments, _cwd = _recorded(folder)
    assert arguments == r'-m spyglass_service.desktop --data "C:\a b\c"'


def test_launcher_with_no_arguments_starts_the_app(tmp_path: Path, programs: dict[str, Path]) -> None:
    """The Start-menu entry passes nothing; Python then gets only the module to run."""
    folder = _install_folder(tmp_path, programs)
    assert _launch(folder, []).returncode == 0
    assert _recorded(folder)[0] == "-m spyglass_service.desktop"


def test_launcher_reports_a_missing_interpreter(tmp_path: Path, programs: dict[str, Path]) -> None:
    """Without the venv's pythonw.exe it names the missing file, says what to do and fails."""
    folder = _install_folder(tmp_path, programs, with_python=False)
    result = _launch(folder, [], SPYGLASS_LAUNCHER_NO_DIALOG="1")
    assert result.returncode == 2
    assert r".venv\Scripts\pythonw.exe" in result.stderr
    assert "installer again" in result.stderr


def test_launcher_carries_the_version_and_name(programs: dict[str, Path]) -> None:
    """Explorer and Task Manager read the release version and the name Spyglass from the file."""
    script = (f"$v = (Get-Item -LiteralPath '{programs['launcher']}').VersionInfo; "
              "@{file=$v.FileVersion; product=$v.ProductVersion; name=$v.ProductName; "
              "description=$v.FileDescription} | ConvertTo-Json -Compress")
    result = subprocess.run([_powershell(), "-NoProfile", "-Command", script], capture_output=True,
                            text=True, timeout=RUN_TIMEOUT_S, check=True)
    info = json.loads(result.stdout)
    assert info == {"file": f"{TEST_VERSION}.0", "product": TEST_VERSION, "name": "Spyglass",
                    "description": "Spyglass"}


@pytest.mark.skipif(shutil.which("powershell") is None, reason="needs Windows PowerShell 5.1")
def test_build_script_runs_in_windows_powershell(tmp_path: Path) -> None:
    """installer/README.md builds with `powershell -File` and the default output path.

    Windows PowerShell 5.1 leaves $PSScriptRoot empty in param() defaults, so the defaults must be
    worked out in the script body. A copy of the build files keeps the real installer\\Spyglass.exe
    untouched.
    """
    installer = tmp_path / "installer"
    (installer / "launcher").mkdir(parents=True)
    shutil.copy2(BUILD_SCRIPT, installer / BUILD_SCRIPT.name)
    shutil.copy2(BUILD_SCRIPT.parent / "spyglass.ico", installer / "spyglass.ico")
    shutil.copy2(BUILD_SCRIPT.parent / "launcher" / "Spyglass.cs", installer / "launcher" / "Spyglass.cs")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(installer / BUILD_SCRIPT.name), "-Version", TEST_VERSION],
        capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installer / "Spyglass.exe").is_file()


def test_build_script_names_a_missing_compiler(tmp_path: Path) -> None:
    """On a machine without the compiler the build stops and says where it looked."""
    missing = tmp_path / "nothing" / "csc.exe"
    result = _run_build(tmp_path / "Spyglass.exe", "-CscPath", str(missing))
    assert result.returncode != 0
    assert str(missing) in result.stdout + result.stderr
    assert not (tmp_path / "Spyglass.exe").exists()
