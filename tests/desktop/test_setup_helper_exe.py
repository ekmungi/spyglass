"""SpyglassSetup.exe, the helper program the MSI runs for the steps Python cannot do itself.

These tests build the real program with installer/build_setup_helper.ps1 (the C# compiler that
comes with the .NET Framework 4.x) and run it in throwaway folders. One small stand-in program
plays uv.exe, pythonw.exe and the old Inno uninstaller and records how it was started; a tiny
HTTP server plays the Spyglass health check; registry tests use a scratch key under
HKCU\\Software\\SpyglassTests. They run only on Windows with the compiler present; nothing here
installs Spyglass or touches the running one.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "installer" / "build_setup_helper.ps1"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
TEST_VERSION = "9.8.7"
# Long enough for a cold .NET start on a busy PC; a hung helper fails instead of blocking the run.
RUN_TIMEOUT_S = 60

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not CSC.is_file(),
    reason="needs Windows and the .NET Framework 4.x C# compiler",
)

# A console program that records its arguments, working folder and UV_ variables into a .rec file
# beside itself (or in STANDIN_REC_DIR), prints one line, optionally sleeps, and exits with the code in STANDIN_EXIT_<NAME>
# (NAME is its file name in capitals). As unins000.exe it also deletes the registry key it is told
# about in SPYGLASS_SETUP_INNO_KEY, unless STANDIN_KEEP_KEY is 1, as the real uninstaller does.
STANDIN_SOURCE = r"""
using System;
using System.Collections;
using System.IO;
using System.Text;
using System.Threading;
using Microsoft.Win32;

class StandIn
{
    static string Rest(string line)
    {
        line = line.TrimStart();
        int end = line.StartsWith("\"") ? line.IndexOf('"', 1) + 1 : line.IndexOfAny(new[] { ' ', '\t' });
        return end <= 0 || end >= line.Length ? "" : line.Substring(end).TrimStart();
    }

    static string Env(string name) { return Environment.GetEnvironmentVariable(name) ?? ""; }

    static int Main()
    {
        string self = System.Reflection.Assembly.GetExecutingAssembly().Location;
        string stem = Path.GetFileNameWithoutExtension(self);
        StringBuilder text = new StringBuilder();
        text.AppendLine("ARGS=" + Rest(Environment.CommandLine));
        text.AppendLine("CWD=" + Environment.CurrentDirectory);
        foreach (DictionaryEntry item in Environment.GetEnvironmentVariables())
        {
            string key = (string)item.Key;
            if (key.StartsWith("UV_", StringComparison.OrdinalIgnoreCase))
                text.AppendLine("ENV:" + key + "=" + item.Value);
        }
        foreach (string folder in new[] { "USERPROFILE", "APPDATA", "LOCALAPPDATA" })
            text.AppendLine("HOME:" + folder + "=" + Env(folder));
        string recordFolder = Env("STANDIN_REC_DIR") != "" ? Env("STANDIN_REC_DIR") : Path.GetDirectoryName(self);
        File.WriteAllText(Path.Combine(recordFolder, stem + ".rec"), text.ToString());
        Console.WriteLine("standin " + stem + " says hi");
        if (stem == "unins000" && Env("STANDIN_KEEP_KEY") != "1" && Env("SPYGLASS_SETUP_INNO_KEY") != "")
            Registry.CurrentUser.DeleteSubKeyTree(Env("SPYGLASS_SETUP_INNO_KEY"), false);
        if (Env("STANDIN_SLEEP_MS") != "") Thread.Sleep(int.Parse(Env("STANDIN_SLEEP_MS")));
        string code = Env("STANDIN_EXIT_" + stem.ToUpperInvariant());
        return code == "" ? 0 : int.Parse(code);
    }
}
"""


def _powershell() -> str:
    """PowerShell 7 when present (the release job's shell), else Windows PowerShell."""
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


def _run_build(out_file: Path) -> subprocess.CompletedProcess[str]:
    """Run the build script for TEST_VERSION, writing the program to `out_file`."""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BUILD_SCRIPT),
         "-Version", TEST_VERSION, "-OutFile", str(out_file)],
        capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False,
    )


@pytest.fixture(scope="module")
def programs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The helper built by the build script, and the stand-in built straight with csc."""
    build = tmp_path_factory.mktemp("build")
    helper = build / "SpyglassSetup.exe"
    result = _run_build(helper)
    assert result.returncode == 0, f"build failed: {result.stdout}\n{result.stderr}"
    source = build / "StandIn.cs"
    source.write_text(STANDIN_SOURCE, encoding="utf-8")
    standin = build / "standin.exe"
    compiled = subprocess.run([str(CSC), "/nologo", "/target:exe", f"/out:{standin}", str(source)],
                              capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False)
    assert compiled.returncode == 0, compiled.stdout
    return {"helper": helper, "standin": standin}


def _delete_registry_tree(path: str) -> None:
    """Delete a key and everything under it in HKCU (winreg has no recursive delete)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_registry_tree(path + "\\" + child)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


@dataclass
class World:
    """One test's throwaway setup: the helper, an install folder, a settings file and the env."""

    helper: Path
    standin: Path
    base: Path
    install: Path = field(init=False)
    config: Path = field(init=False)
    env: dict[str, str] = field(init=False)
    registry_root: str = field(init=False)

    def __post_init__(self) -> None:
        self.install = self.base / "Spy glass"
        self.install.mkdir()
        self.config = self.base / "cfg" / "desktop.json"
        self.config.parent.mkdir()
        self.registry_root = f"Software\\SpyglassTests\\{uuid.uuid4().hex}"
        self.env = {**os.environ, "SPYGLASS_DESKTOP_CONFIG": str(self.config),
                    "SPYGLASS_LAUNCHER_NO_DIALOG": "1",
                    "SPYGLASS_SETUP_FEATURES_KEY": self.registry_root + "\\Features",
                    "SPYGLASS_SETUP_INNO_KEY": self.registry_root + "\\inno",
                    "SPYGLASS_SETUP_RUN_KEY": self.registry_root + "\\Run"}

    def place(self, relative: str) -> Path:
        """Copy the stand-in to `relative` under the install folder and return its path."""
        target = self.install / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.standin, target)
        return target

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        """Run the helper with `args`, plus extra environment values."""
        return subprocess.run([str(self.helper), *args], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT_S, env={**self.env, **env}, cwd=self.base, check=False)

    def command(self, name: str, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
        """Run command `name` on the install folder."""
        return self.run(name, "--install-dir", str(self.install), *extra, **env)

    def log(self) -> str:
        """The text of install.log, empty when none was written."""
        path = self.config.parent / "install.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def set_port(self, port: int) -> None:
        """Write desktop.json with the port the fake service listens on."""
        self.config.write_text(json.dumps({"data_dir": "x", "port": port}), encoding="utf-8")

    def create_key(self, name: str, **values: str) -> None:
        """Create HKCU\\<registry_root>\\<name> with string values."""
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{self.registry_root}\\{name}") as key:
            for value_name, data in values.items():
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, data)

    def key_exists(self, name: str) -> bool:
        """Whether HKCU\\<registry_root>\\<name> exists."""
        import winreg
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{self.registry_root}\\{name}"))
            return True
        except FileNotFoundError:
            return False


@pytest.fixture
def world(programs: dict[str, Path], tmp_path: Path):
    """A fresh World; its scratch registry keys are always removed afterwards."""
    w = World(programs["helper"], programs["standin"], tmp_path)
    try:
        yield w
    finally:
        _delete_registry_tree(w.registry_root)


def _record(program: Path) -> dict:
    """What a stand-in recorded: its arguments, working folder and UV_ variables."""
    lines = program.with_suffix(".rec").read_text(encoding="utf-8").splitlines()
    result: dict = {"env": {}, "home": {}}
    for line in lines:
        if line.startswith("ENV:"):
            name, _, value = line[4:].partition("=")
            result["env"][name.upper()] = value
        elif line.startswith("HOME:"):
            name, _, value = line[5:].partition("=")
            result["home"][name.upper()] = value
        else:
            name, _, value = line.partition("=")
            result[name.lower()] = value
    return result


@dataclass
class FakeService:
    """A stand-in Spyglass health endpoint; it records POSTs and stops answering on shutdown."""

    server: http.server.ThreadingHTTPServer
    posts: list[str]

    @property
    def port(self) -> int:
        return self.server.server_address[1]


@pytest.fixture
def service_factory():
    """Start fake services on free ports and stop every one at the end of the test."""
    started: list[FakeService] = []

    def start(health_body: str) -> FakeService:
        posts: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # one request per connection, so a closed port stays closed

            def _reply(self, text: str) -> None:
                data = text.encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                self._reply(health_body)

            def do_POST(self) -> None:  # noqa: N802
                posts.append(self.path)
                self._reply("{}")
                threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True).start()

            def log_message(self, *args: object) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        service = FakeService(server, posts)
        started.append(service)
        return service

    yield start
    for service in started:
        try:
            service.server.shutdown()
            service.server.server_close()
        except OSError:
            pass


DESKTOP_HEALTH = json.dumps({"status": "ok", "version": "0.41.1", "started_by": "desktop"})
DEVELOPER_HEALTH = json.dumps({"status": "ok", "version": "0.41.1", "started_by": "developer"})


# ---- the program itself ----------------------------------------------------------------------

def test_helper_carries_the_version_and_name(programs: dict[str, Path]) -> None:
    """Explorer and the MSI log read the release version and the name Spyglass Setup from the file."""
    script = (f"$v = (Get-Item -LiteralPath '{programs['helper']}').VersionInfo; "
              "@{file=$v.FileVersion; product=$v.ProductVersion; name=$v.ProductName; "
              "company=$v.CompanyName} | ConvertTo-Json -Compress")
    result = subprocess.run([_powershell(), "-NoProfile", "-Command", script], capture_output=True,
                            text=True, timeout=RUN_TIMEOUT_S, check=True)
    assert json.loads(result.stdout) == {"file": f"{TEST_VERSION}.0", "product": TEST_VERSION,
                                         "name": "Spyglass Setup", "company": "ekmungi"}


def test_build_script_defaults_work_under_windows_powershell(tmp_path: Path) -> None:
    """With no -OutFile the script writes installer\\SpyglassSetup.exe next to itself (PowerShell 5.1)."""
    installer = tmp_path / "installer"
    (installer / "setup").mkdir(parents=True)
    shutil.copy2(BUILD_SCRIPT, installer / BUILD_SCRIPT.name)
    for source in (BUILD_SCRIPT.parent / "setup").glob("*.cs"):
        shutil.copy2(source, installer / "setup" / source.name)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(installer / BUILD_SCRIPT.name), "-Version", TEST_VERSION],
        capture_output=True, text=True, timeout=RUN_TIMEOUT_S, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installer / "SpyglassSetup.exe").is_file()


@pytest.mark.parametrize("args", [
    [], ["frobnicate", "--install-dir", "x"], ["prepare"], ["prepare", "--install-dir"],
    ["prepare", "--install-dir", "x", "--ui", "loud"], ["prepare", "--install-dir", "x", "--bogus"],
])
def test_bad_command_line_prints_usage_and_exits_2(world: World, args: list[str]) -> None:
    """A missing or unknown command, option or value is a usage error, not a setup failure."""
    result = world.run(*args)
    assert result.returncode == 2
    assert "Usage" in result.stderr


def test_trailing_backslash_inside_quotes_is_kept_out_of_the_folder(world: World) -> None:
    """The MSI passes the install folder with a trailing backslash, which swallows a closing quote."""
    world.place(".venv/Scripts/pythonw.exe")
    (world.install / ".venv-being-built").write_text("x")  # undoing a first install
    result = subprocess.run(
        f'"{world.helper}" remove-environment --install-dir "{world.install}\\"',
        capture_output=True, text=True, timeout=RUN_TIMEOUT_S, env=world.env, check=False)
    assert result.returncode == 0, result.stderr
    assert not (world.install / ".venv").exists()


def test_the_folder_form_the_package_passes_reaches_python_clean(world: World) -> None:
    """The package passes "[INSTALLFOLDER]." (a dot keeps the backslash off the quote); the
    helper hands Python the plain folder."""
    world.set_port(1)  # never 7777, where a real Spyglass may run
    world.place(".venv/Scripts/pythonw.exe")
    result = subprocess.run(
        f'"{world.helper}" uninstall --install-dir "{world.install}\\." --ui 2',
        capture_output=True, text=True, timeout=RUN_TIMEOUT_S, env=world.env, check=False)
    assert result.returncode == 0, result.stderr
    assert f'--install-dir "{world.install}"' in world.log()


# ---- prepare ---------------------------------------------------------------------------------

def test_prepare_with_nothing_running_exits_0_and_writes_the_log(world: World) -> None:
    """With no service, no program from the folder and no old install, prepare only logs."""
    world.set_port(1)  # nothing listens on port 1
    result = world.command("prepare", "--ui", "2")
    assert result.returncode == 0, result.stderr
    log = world.log()
    assert f"--- Spyglass Setup {TEST_VERSION} prepare, " in log
    assert not (world.config.parent / "install.log").read_bytes().startswith(b"\xef\xbb\xbf")


def test_prepare_stops_a_service_the_desktop_app_started(world: World, service_factory) -> None:
    """A desktop-started service gets a POST to /api/shutdown and is waited for until its port is free."""
    service = service_factory(DESKTOP_HEALTH)
    world.set_port(service.port)
    result = world.command("prepare")
    assert result.returncode == 0, result.stderr
    assert service.posts == ["/api/shutdown"]
    assert "stopped" in world.log().lower()


@pytest.mark.parametrize("body", [DEVELOPER_HEALTH, '{"hello": "world"}'])
def test_prepare_leaves_a_service_the_app_did_not_start(world: World, service_factory, body: str) -> None:
    """A developer copy, an old version or another program on the port is left alone."""
    service = service_factory(body)
    world.set_port(service.port)
    result = world.command("prepare")
    assert result.returncode == 0
    assert service.posts == []
    if "developer" in body:
        assert "not started by the Spyglass app" in result.stderr


def test_prepare_refuses_while_a_program_runs_from_the_install_folder(world: World) -> None:
    """Replacing files under a running program fails, so prepare asks the user to quit Spyglass."""
    sleeper = world.place("sleeper.exe")
    process = subprocess.Popen([str(sleeper)], env={**world.env, "STANDIN_SLEEP_MS": "60000"},
                               stdout=subprocess.DEVNULL)
    try:
        deadline = time.time() + 20
        while not sleeper.with_suffix(".rec").exists() and time.time() < deadline:
            time.sleep(0.1)
        world.set_port(1)
        result = world.command("prepare")
    finally:
        process.kill()
        process.wait()
    assert result.returncode == 1
    assert "is still running from" in result.stderr and str(world.install) in result.stderr


def test_prepare_removes_an_old_inno_install(world: World) -> None:
    """The old uninstaller is run silently, and prepare waits until its uninstall key is gone."""
    old = world.base / "old"
    old.mkdir()
    shutil.copy2(world.standin, old / "unins000.exe")
    world.create_key("inno", UninstallString=f'"{old / "unins000.exe"}" /ignored')
    world.set_port(1)
    result = world.command("prepare")
    assert result.returncode == 0, result.stderr
    assert _record(old / "unins000.exe")["args"] == "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
    assert not world.key_exists("inno")
    assert "unins000.exe" in world.log()


def test_prepare_fails_when_the_old_uninstaller_leaves_its_key(world: World) -> None:
    """A key that outlives the uninstaller means the old install is still there: tell the user how."""
    old = world.base / "old"
    old.mkdir()
    shutil.copy2(world.standin, old / "unins000.exe")
    world.create_key("inno", UninstallString=f'"{old / "unins000.exe"}"')
    world.set_port(1)
    result = world.command("prepare", STANDIN_KEEP_KEY="1", SPYGLASS_SETUP_WAIT_S="1")
    assert result.returncode == 1
    assert "Remove Spyglass in Settings > Apps > Installed apps" in result.stderr


def test_prepare_fails_when_the_old_uninstaller_is_missing(world: World) -> None:
    """A key that names a program that is gone cannot be removed by Setup either."""
    world.create_key("inno", UninstallString=f'"{world.base / "gone" / "unins000.exe"}"')
    world.set_port(1)
    result = world.command("prepare", SPYGLASS_SETUP_WAIT_S="1")
    assert result.returncode == 1
    assert "Settings > Apps" in result.stderr


# ---- environment -----------------------------------------------------------------------------

def test_environment_runs_uv_then_the_python_step(world: World) -> None:
    """uv gets the locked sync arguments, the ticked extras and its variables; Python gets none of them."""
    world.create_key("Features", **{"pdf": "1", "local-ai": "1"})
    uv = world.place("uv.exe")
    pythonw = world.place(".venv/Scripts/pythonw.exe")
    result = world.command("environment", UV_CACHE_DIR="poison")
    assert result.returncode == 0, result.stderr
    ran = _record(uv)
    assert ran["args"] == "sync --frozen --no-dev --python 3.13 --extra pdf --extra local-ai"
    assert ran["cwd"] == str(world.install)
    install = str(world.install)
    cache = ran["env"]["UV_CACHE_DIR"]
    expected = {
        "UV_PYTHON_INSTALL_DIR": install + "\\python", "UV_PROJECT_ENVIRONMENT": install + "\\.venv",
        "UV_LINK_MODE": "copy", "UV_MANAGED_PYTHON": "1", "UV_PYTHON_INSTALL_BIN": "0",
        "UV_PYTHON_INSTALL_REGISTRY": "0", "UV_COMPILE_BYTECODE": "1"}
    assert expected.items() <= ran["env"].items()
    assert cache != "poison" and not Path(cache).exists()
    python = _record(pythonw)
    assert python["args"] == f'-I -X utf8 -m spyglass_service.desktop.setup_steps install --install-dir "{install}"'
    assert python["cwd"] == install
    assert python["env"] == {}
    assert "standin uv says hi" in world.log()


@pytest.mark.parametrize(("features", "extras"), [({}, ""), ({"pdf": "1", "local-ai": "0"}, " --extra pdf"),
                                                   ({"local-ai": "1"}, " --extra local-ai")])
def test_environment_adds_only_the_ticked_extras(world: World, features: dict, extras: str) -> None:
    """Only a feature value of "1" adds its uv extra; a missing key or value means unticked."""
    if features:
        world.create_key("Features", **features)
    uv = world.place("uv.exe")
    world.place(".venv/Scripts/pythonw.exe")
    assert world.command("environment").returncode == 0
    assert _record(uv)["args"] == "sync --frozen --no-dev --python 3.13" + extras


def test_environment_fails_when_uv_fails(world: World) -> None:
    """A failed uv stops setup with the log's path in the message, and the Python step does not run."""
    world.place("uv.exe")
    pythonw = world.place(".venv/Scripts/pythonw.exe")
    result = world.command("environment", STANDIN_EXIT_UV="3")
    assert result.returncode == 1
    assert "could not prepare Python" in result.stderr
    assert str(world.config.parent / "install.log") in result.stderr
    assert not pythonw.with_suffix(".rec").exists()


def test_environment_fails_when_uv_is_missing(world: World) -> None:
    """A missing uv.exe is the same failure as a failing one."""
    assert world.command("environment").returncode == 1


def test_a_failing_python_step_does_not_fail_environment(world: World) -> None:
    """The Python step writes its own lines to the log; its exit code is logged, never fatal."""
    world.place("uv.exe")
    world.place(".venv/Scripts/pythonw.exe")
    result = world.command("environment", STANDIN_EXIT_PYTHONW="5")
    assert result.returncode == 0
    assert "Exit code 5" in world.log()


# ---- remove-environment and uninstall --------------------------------------------------------

def _make_environment(world: World) -> None:
    """Fill the install folder with an environment, caches, and files that must stay."""
    deep = world.install / ".venv" / "Lib"
    deep_text = "\\\\?\\" + str(deep) + "".join(f"\\{'d' * 12}" for _ in range(25))
    os.makedirs(deep_text)  # past 260 characters, as uv's deepest folders can be
    (world.install / "python").mkdir()
    (world.install / "python" / "python.exe").write_text("x")
    for folder in ("src/pkg/__pycache__", "src/__pycache__", "src/pkg/sub/__pycache__"):
        (world.install / folder).mkdir(parents=True)
        (world.install / folder / "a.pyc").write_text("x")
    (world.install / "src" / "pkg" / "mod.py").write_text("x")
    (world.install / "uv.exe").write_text("x")


def test_remove_environment_deletes_the_environment_and_caches_only(world: World) -> None:
    """Undoing a first install: .venv, python and every __pycache__ under src go; other files stay;
    missing folders are fine."""
    _make_environment(world)
    (world.install / ".venv-being-built").write_text("x")  # this setup was building it
    result = world.command("remove-environment")
    assert result.returncode == 0, result.stderr
    assert not (world.install / ".venv").exists() and not (world.install / "python").exists()
    assert not list((world.install / "src").rglob("__pycache__"))
    assert (world.install / "src" / "pkg" / "mod.py").is_file() and (world.install / "uv.exe").is_file()
    assert world.command("remove-environment").returncode == 0  # nothing left to remove


def test_uninstall_runs_the_python_uninstall_step_then_removes_the_environment(world: World) -> None:
    """Python gets its own clean-up first, while its interpreter still exists; then the folders go."""
    world.place(".venv/Scripts/pythonw.exe")
    world.set_port(1)
    result = world.command("uninstall", STANDIN_REC_DIR=str(world.base))  # .venv is deleted afterwards
    assert result.returncode == 0, result.stderr
    args = _record(world.base / "pythonw.exe")["args"]
    assert args == f'-I -X utf8 -m spyglass_service.desktop.setup_steps uninstall --install-dir "{world.install}"'
    assert not (world.install / ".venv").exists()


def test_uninstall_stops_a_desktop_service(world: World, service_factory) -> None:
    """Uninstall stops the desktop-started service as prepare does."""
    service = service_factory(DESKTOP_HEALTH)
    world.set_port(service.port)
    assert world.command("uninstall").returncode == 0
    assert service.posts == ["/api/shutdown"]


# ---- what a failed or cancelled setup leaves -------------------------------------------------

def test_rolling_back_keeps_an_environment_that_was_there_before(world: World) -> None:
    """A Modify or upgrade that fails (offline, or cancelled) must not delete a working Spyglass."""
    _make_environment(world)
    world.place("uv.exe")
    assert world.command("environment", STANDIN_EXIT_UV="3").returncode == 1
    assert world.command("remove-environment").returncode == 0
    assert (world.install / ".venv").is_dir() and (world.install / "python").is_dir()


def test_rolling_back_a_first_install_deletes_the_half_built_environment(world: World) -> None:
    world.place("uv.exe")
    assert world.command("environment", STANDIN_EXIT_UV="3").returncode == 1
    (world.install / ".venv" / "Lib").mkdir(parents=True)  # what uv left before it failed
    assert world.command("remove-environment").returncode == 0
    assert not (world.install / ".venv").exists()
    assert not any(p.name.startswith(".venv-") for p in world.install.iterdir())


def test_a_successful_build_is_kept_by_a_later_rollback(world: World) -> None:
    world.place("uv.exe")
    world.place(".venv/Scripts/pythonw.exe")
    assert world.command("environment").returncode == 0
    assert world.command("remove-environment").returncode == 0
    assert (world.install / ".venv" / "Scripts" / "pythonw.exe").is_file()


def test_the_python_step_gets_the_signed_in_users_folders(world: World) -> None:
    """Setup may run with another environment; Spyglass's code finds Claude Code and uv's tool
    folder through these variables, so the helper sets them from the user's own folders."""
    world.place("uv.exe")
    pythonw = world.place(".venv/Scripts/pythonw.exe")
    result = world.command("environment", USERPROFILE=r"C:\wrong", APPDATA=r"C:\wrong")
    assert result.returncode == 0, result.stderr
    home = _record(pythonw)["home"]
    assert home["USERPROFILE"] == str(Path.home())
    assert home["APPDATA"] == os.environ["APPDATA"] and home["LOCALAPPDATA"] == os.environ["LOCALAPPDATA"]


def test_uninstall_without_python_still_removes_this_installs_start_up_entry(world: World) -> None:
    import winreg

    world.set_port(1)
    world.create_key("Run", Spyglass=f'"{world.install / "Spyglass.exe"}" --background')
    assert world.command("uninstall").returncode == 0
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, world.registry_root + r"\Run") as key:
        with pytest.raises(FileNotFoundError):
            winreg.QueryValueEx(key, "Spyglass")


def test_uninstall_keeps_a_start_up_entry_of_another_copy(world: World) -> None:
    import winreg

    world.set_port(1)
    world.create_key("Run", Spyglass=r'"D:\dev\spyglass\.venv\Scripts\pythonw.exe" -m x')
    assert world.command("uninstall").returncode == 0
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, world.registry_root + r"\Run") as key:
        assert winreg.QueryValueEx(key, "Spyglass")[0].startswith('"D:')
