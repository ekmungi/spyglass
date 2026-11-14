"""Static checks of the Windows installer script, its icon tool, the release job and the version.

The installer can only be run on a real Windows PC (installer/README.md says how). These tests
read the Inno Setup script as text and pin the rules it must keep: it installs per user, ships
what the service needs, writes the settings file only after the data folder check passed, and
never stops a Spyglass that the desktop app did not start.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
from PIL import Image

import spyglass_service
from spyglass_service.desktop import platform_windows, tray

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"
EXPECTED_VERSION = "0.41.0"
ICON_SIZES = {(16, 16), (32, 32), (48, 48), (256, 256)}


def _read(path: Path) -> str:
    """The file's text, or "" when it does not exist yet (so a test fails instead of erroring)."""
    return path.read_text(encoding="utf-8") if path.is_file() else ""


ISS = _read(INSTALLER / "spyglass.iss")
RELEASE = _read(ROOT / ".github" / "workflows" / "release.yml")


def _section(name: str) -> str:
    """The lines of one [Section] of the script, up to the next section header."""
    match = re.search(rf"^\[{name}\]\s*$(.*?)(?=^\[|\Z)", ISS, re.MULTILINE | re.DOTALL)
    assert match, f"the script has no [{name}] section"
    return match.group(1)


def _routine(name: str) -> str:
    """The text of one [Code] procedure or function, from its header to the next routine."""
    match = re.search(rf"^(?:procedure|function) {name}\b", ISS, re.MULTILINE)
    assert match, f"[Code] has no routine named {name}"
    rest = ISS[match.end():]
    following = re.search(r"^(?:procedure|function) ", rest, re.MULTILINE)
    return rest[: following.start()] if following else rest


def _files_entry(source: str) -> str:
    """The [Files] line that copies `source` (as written after Source:)."""
    for line in _section("Files").splitlines():
        if line.startswith(f'Source: "{source}"'):
            return line
    raise AssertionError(f"[Files] does not copy {source}")


def test_installer_is_per_user() -> None:
    """No administrator rights: the program lands in the user's own Programs folder."""
    assert "PrivilegesRequired=lowest" in ISS
    assert r"DefaultDirName={localappdata}\Programs\Spyglass" in ISS


def test_installer_has_a_fixed_app_id_and_a_versioned_file_name() -> None:
    """A fixed AppId lets a newer installer replace the older version in place."""
    assert re.search(r'^#define AppGuid "[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}"$', ISS,
                     re.MULTILINE)
    assert "AppId={{{#AppGuid}}" in ISS
    assert "OutputBaseFilename=Spyglass-Setup-{#AppVersion}" in ISS


def test_installer_never_clears_a_folder_it_did_not_install() -> None:
    """Upgrades replace the program folders whole, so that may happen only in the folder of an
    earlier install, and a non-empty folder that is not one is refused."""
    for line in _section("InstallDelete").splitlines():
        if line.startswith("Type:"):
            assert "Check: IsEarlierInstallFolder" in line, line
    assert "InstallLocation" in _routine("IsEarlierInstall")
    # Checked where every install passes (the folder page is skipped on an upgrade, yet /DIR
    # still applies), before the stop and before any file is touched.
    prepare = _routine("PrepareToInstall")
    assert "not FolderIsEmpty(Dir) and not IsEarlierInstall(Dir)" in prepare
    assert prepare.index("ForeignFolderMessage(") < prepare.index("StopDesktopSpyglass(")


@pytest.mark.parametrize(
    ("source", "dest"),
    [
        (r"..\src\*", r"{app}\src"),
        (r"..\frontend\dist\*", r"{app}\frontend\dist"),
        (r"..\browser-extension\*", r"{app}\browser-extension"),
        (r"..\pyproject.toml", "{app}"),
        (r"..\uv.lock", "{app}"),
        (r"..\README.md", "{app}"),
        (r"..\LICENSE", "{app}"),
        ("uv.exe", "{app}"),
    ],
)
def test_installer_ships_what_the_service_needs(source: str, dest: str) -> None:
    """The installed folder keeps the repository layout the service looks for."""
    assert f'DestDir: "{dest}"' in _files_entry(source)


def test_installer_ships_the_skills_folder() -> None:
    """The service copies the skills into the vault at every start, so they must be installed."""
    entry = _files_entry(r"..\skills\*")
    assert r'DestDir: "{app}\skills"' in entry
    assert "recursesubdirs" in entry


def test_installer_excludes_extension_tests_and_tools() -> None:
    """The extension's tests and developer tools are not part of the installed extension."""
    excludes = re.search(r'Excludes: "([^"]*)"', _files_entry(r"..\browser-extension\*"))
    assert excludes, "the browser-extension entry has no Excludes"
    patterns = excludes.group(1).split(",")
    assert r"\tests" in patterns
    assert r"\tools" in patterns


def test_installer_puts_the_icon_where_the_tray_looks() -> None:
    """The tray reads <root>/installer/spyglass.ico, in the repository and when installed."""
    assert r'DestDir: "{app}\installer"' in _files_entry("spyglass.ico")
    assert tray.ICON_PATH.relative_to(ROOT) == Path("installer") / "spyglass.ico"


def test_installer_sets_up_python_in_its_own_folders() -> None:
    """uv builds the environment inside the install folder from the lock file, then its
    temporary cache is deleted."""
    body = _routine("InstallEnvironment")
    assert "sync --frozen --no-dev --python 3.13" in body
    for name in ("UV_PYTHON_INSTALL_DIR", "UV_PROJECT_ENVIRONMENT", "UV_LINK_MODE", "UV_CACHE_DIR"):
        assert f"'{name}'" in body, name
    # Nothing outside the install folder may point into it after an uninstall.
    assert "SetEnvironmentVariable('UV_PYTHON_INSTALL_BIN', '0')" in body
    assert "SetEnvironmentVariable('UV_PYTHON_INSTALL_REGISTRY', '0')" in body
    assert "'copy'" in body
    assert "DelTree(Cache" in body
    assert "install.log" in ISS


def test_installer_writes_desktop_json_only_after_the_folder_check() -> None:
    """The settings file is written after the check, and a refused folder stops before it."""
    body = _routine("SetUpSpyglass")
    environment = body.index("InstallEnvironment")
    check = body.index("RunFolderCheck(")
    write = body.index("WriteDesktopConfig(")
    assert environment < check < write
    assert "Exit;" in body[check:write], "a refused folder must leave before desktop.json is written"
    assert "--check-data-dir" in _routine("RunFolderCheck")


def test_installer_stops_only_a_spyglass_the_app_started() -> None:
    """A developer Spyglass (such as the live copy on 7777) must never be stopped: the script
    reads started_by from /api/health before it may call /api/shutdown."""
    assert ISS.count("/api/shutdown") == 1, "only one place may ask a Spyglass to stop"
    body = _routine("StopDesktopSpyglass")
    assert body.index("IsStartedByDesktop(") < body.index("/api/shutdown")
    assert "not IsStartedByDesktop(" in body
    assert "'\"started_by\":\"desktop\"'" in _routine("IsStartedByDesktop")


def test_start_menu_entry_and_startup_value_match_the_app() -> None:
    """The Start-menu entry opens the windowless app; the Run value is the one the app manages."""
    shortcut = _routine("CreateStartMenuEntry")
    assert r"\.venv\Scripts\pythonw.exe" in ISS
    assert "'-m spyglass_service.desktop'" in shortcut
    assert f"RunKey = '{platform_windows.RUN_KEY}';" in ISS
    assert f"RunValue = '{platform_windows.RUN_VALUE}';" in ISS
    # The same command line the app writes when Start with Windows is switched on.
    assert '" -m spyglass_service.desktop --background' in _routine("ApplyAutostart")


def test_installer_removes_the_old_scheduled_task() -> None:
    """The scheduled task the old start-up script made would race the new start-up entry."""
    body = _routine("RemoveOldScheduledTask")
    assert body.index("/Query /TN Spyglass") < body.index("/Delete /TN Spyglass /F")


def test_uninstaller_keeps_the_data_and_the_settings_file() -> None:
    """Uninstall removes the program and the start-up entry, never the data or desktop.json."""
    removed = re.findall(r'Name: "([^"]*)"', _section("UninstallDelete"))
    assert r"{app}\.venv" in removed
    assert not [name for name in removed if not name.startswith(("{app}", "{userprograms}"))]
    assert not [name for name in removed if "desktop.json" in name]
    uninstall = _routine("CurUninstallStepChanged")
    assert "StopDesktopSpyglass(" in uninstall
    assert "RemoveAutostartIfOurs" in uninstall
    # uv's environment holds paths past 260 characters, which only a \\?\ path can delete.
    assert r"RemoveDeepFolder(ExpandConstant('{app}\.venv'))" in uninstall
    assert r"RemoveDeepFolder(ExpandConstant('{app}\python'))" in uninstall
    assert r"\\?\'" in _routine("RemoveDeepFolder")


def test_release_job_builds_and_uploads_the_installer() -> None:
    """A Windows job builds the interface, checks the pinned uv, compiles and uploads."""
    assert re.search(r"^  installer:\s*$", RELEASE, re.MULTILINE)
    assert "runs-on: windows-latest" in RELEASE
    assert "npm ci" in RELEASE
    assert re.search(r"[0-9a-f]{64}", RELEASE), "the uv download needs a pinned SHA-256"
    assert "Get-FileHash" in RELEASE
    assert "/DAppVersion=" in RELEASE
    assert r"installer\spyglass.iss" in RELEASE
    assert "gh release upload" in RELEASE
    assert "Spyglass-Setup-" in RELEASE


def test_the_tag_check_runs_before_anything_is_published() -> None:
    """A tag that differs from the code's version stops the release in its first job, before the
    plugin files are published; the installer job needs that job, so it never runs either."""
    release_job, installer_job = RELEASE.split("\n  installer:", 1)
    check = "name: Check the tag matches the version in the code"
    assert check in release_job and check not in installer_job
    first_steps = release_job.index("actions/checkout"), release_job.index(check)
    assert first_steps[0] < first_steps[1] < release_job.index("name: Build plugin bundle")
    assert release_job.index(check) < release_job.index("Publish release with plugin assets")
    step = release_job[release_job.index(check):release_job.index("name: Build plugin bundle")]
    assert "TAG: ${{ github.ref_name }}" in step  # the tag reaches the script through env only
    assert "manifest.json" in step and "__version__" in step
    assert "needs: release" in installer_job


def test_versions_agree() -> None:
    """Every place that names the version names the same one."""
    plugin = json.loads(_read(ROOT / "manifest.json"))
    extension = json.loads(_read(ROOT / "browser-extension" / "manifest.json"))
    versions = json.loads(_read(ROOT / "versions.json"))
    assert spyglass_service.__version__ == EXPECTED_VERSION
    assert plugin["version"] == EXPECTED_VERSION
    assert extension["version"] == EXPECTED_VERSION
    assert list(versions)[-1] == EXPECTED_VERSION
    assert versions[EXPECTED_VERSION] == plugin["minAppVersion"]


def _load_make_icon():
    """Import installer/make_icon.py, which is a script and not part of the package."""
    spec = importlib.util.spec_from_file_location("make_icon", INSTALLER / "make_icon.py")
    assert spec and spec.loader, "installer/make_icon.py is missing"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_make_icon_writes_the_four_sizes(tmp_path: Path) -> None:
    """The icon tool turns the extension's 128-pixel icon into a 16, 32, 48 and 256 icon."""
    target = tmp_path / "out.ico"
    _load_make_icon().make_icon(ROOT / "browser-extension" / "icons" / "icon-128.png", target)
    with Image.open(target) as icon:
        assert set(icon.info["sizes"]) == ICON_SIZES


def test_committed_icon_has_the_four_sizes() -> None:
    """The icon in the repository is the tool's output, so the build needs no Pillow step."""
    with Image.open(INSTALLER / "spyglass.ico") as icon:
        assert set(icon.info["sizes"]) == ICON_SIZES
