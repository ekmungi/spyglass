"""Static checks of the release workflow and the version, which the Windows installer depends on.

The release job builds the plugin and publishes a release for a version tag; its Windows job
builds the launcher, the setup helper, the MSI package and the setup .exe. A test tag runs the same
build and publishes nothing. These tests read the workflow as text, and run its tag check.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import spyglass_service

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.43.0"
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
RELEASE_JOB, INSTALLER_JOB = RELEASE.split("\n  installer:", 1)


def _step(job: str, name: str) -> str:
    """The text of one step of `job`, from its name to the next step."""
    start = job.index(f"name: {name}")
    following = job.find("\n      - ", start)
    return job[start:] if following < 0 else job[start:following]


def test_installer_job_builds_the_msi_with_a_pinned_uv_and_wix() -> None:
    """A Windows job builds the interface, checks the pinned uv and builds with WiX 5.0.2."""
    assert "runs-on: windows-latest" in INSTALLER_JOB
    assert "npm ci" in INSTALLER_JOB
    assert re.search(r'UV_ZIP_SHA256: "[0-9a-f]{64}"', INSTALLER_JOB)
    assert "Get-FileHash" in INSTALLER_JOB
    assert 'WIX_VERSION: "5.0.2"' in INSTALLER_JOB
    assert r"installer\build_msi.ps1 -Version $env:VERSION" in INSTALLER_JOB
    assert "iscc" not in RELEASE.lower() and "spyglass.iss" not in RELEASE


def test_both_programs_are_compiled_before_the_package_is_built() -> None:
    """The package embeds Spyglass.exe and the setup helper, built with the local build's scripts."""
    package = INSTALLER_JOB.index(r"installer\build_msi.ps1")
    for script in (r"installer\build_launcher.ps1", r"installer\build_setup_helper.ps1"):
        assert INSTALLER_JOB.index(f"{script} -Version $env:VERSION") < package
    step = _step(INSTALLER_JOB, "Build Spyglass.exe and the setup helper")
    assert step.count("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }") == 2


def test_wix_and_the_three_extensions_are_installed() -> None:
    step = _step(INSTALLER_JOB, "Install WiX and its extensions")
    assert "dotnet tool install --global wix --version $env:WIX_VERSION" in step
    for extension in ("WixToolset.UI.wixext", "WixToolset.Util.wixext",
                      "WixToolset.BootstrapperApplications.wixext"):
        assert extension in step


def test_a_version_tag_publishes_the_msi_and_never_the_setup_exe() -> None:
    """The setup .exe stays off the release until it has passed the Start-menu test."""
    upload = _step(INSTALLER_JOB, "Upload the MSI to the release")
    assert "if: needs.release.outputs.test != 'true'" in upload
    assert r'"installer\Output\Spyglass-$env:VERSION.msi"' in upload
    assert "gh release upload" in upload
    assert "Spyglass-Setup-" not in upload
    exe = _step(INSTALLER_JOB, "Attach the setup .exe to the workflow run")
    assert "actions/upload-artifact@" in exe and "if:" not in exe


def test_a_test_tag_builds_everything_without_publishing() -> None:
    """A test tag attaches the MSI to the run and publishes no release, so BRAT never sees it."""
    publish = _step(RELEASE_JOB, "Publish release with plugin assets")
    assert "if: steps.tag.outputs.test != 'true'" in publish
    assert "version: ${{ steps.tag.outputs.version }}" in RELEASE_JOB
    assert "test: ${{ steps.tag.outputs.test }}" in RELEASE_JOB
    artifact = _step(INSTALLER_JOB, "Attach the MSI to the workflow run (test tags)")
    assert "if: needs.release.outputs.test == 'true'" in artifact


def test_the_tag_check_runs_before_anything_is_published() -> None:
    """A tag that differs from the code's version stops the release in its first job, before the
    plugin files are published; the installer job needs that job, so it never runs either."""
    check = "name: Check the tag matches the version in the code"
    assert check in RELEASE_JOB and check not in INSTALLER_JOB
    assert RELEASE_JOB.index("actions/checkout") < RELEASE_JOB.index(check)
    assert RELEASE_JOB.index(check) < RELEASE_JOB.index("name: Build plugin bundle")
    step = _step(RELEASE_JOB, "Check the tag matches the version in the code")
    assert "TAG: ${{ github.ref_name }}" in step  # the tag reaches the script through env only
    assert "manifest.json" in step and "__version__" in step
    assert "needs: release" in INSTALLER_JOB


def _tag_check_script() -> str:
    """The Python the release job runs to check the tag, cut out of the workflow file."""
    body = RELEASE_JOB.split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(body)


def _run_tag_check(tmp_path: Path, tag: str, code_version: str = "0.42.0") -> tuple[int, str]:
    """Run the release job's tag check for `tag` against code at `code_version`; return its exit
    code and what it wrote to the step's output file."""
    (tmp_path / "src" / "spyglass_service").mkdir(parents=True)
    (tmp_path / "manifest.json").write_text(json.dumps({"version": code_version}), encoding="utf-8")
    (tmp_path / "src" / "spyglass_service" / "__init__.py").write_text(
        f'__version__ = "{code_version}"\n', encoding="utf-8")
    output = tmp_path / "github-output.txt"
    output.write_text("", encoding="utf-8")
    env = {**os.environ, "TAG": tag, "GITHUB_OUTPUT": str(output)}
    done = subprocess.run(  # noqa: S603 -- this interpreter, the workflow's own script
        [sys.executable, "-c", _tag_check_script()], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False)
    return done.returncode, output.read_text(encoding="utf-8")


@pytest.mark.parametrize(("tag", "test_build"), [("0.42.0", "false"), ("0.42.0-test1", "true"),
                                                 ("v0.42.0-test12", "true")])
def test_a_version_tag_or_a_test_tag_passes_the_check(tmp_path: Path, tag: str,
                                                      test_build: str) -> None:
    """A release tag and a test tag both name the code's version; only the test tag is marked."""
    code, written = _run_tag_check(tmp_path, tag)
    assert code == 0
    assert "version=0.42.0" in written.splitlines()
    assert f"test={test_build}" in written.splitlines()


@pytest.mark.parametrize("tag", ["0.42.1", "0.42.1-test1", "0.42.0-rc1", "0.42.0-test", "latest"])
def test_a_tag_that_is_not_the_codes_version_stops_the_release(tmp_path: Path, tag: str) -> None:
    """A tag naming another version, or one that is neither a version nor a test tag, fails."""
    code, written = _run_tag_check(tmp_path, tag)
    assert code != 0
    assert written == ""


def test_versions_agree() -> None:
    """Every place that names the version names the same one."""
    plugin = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    extension = json.loads((ROOT / "browser-extension" / "manifest.json").read_text(encoding="utf-8"))
    versions = json.loads((ROOT / "versions.json").read_text(encoding="utf-8"))
    assert spyglass_service.__version__ == EXPECTED_VERSION
    assert plugin["version"] == EXPECTED_VERSION
    assert extension["version"] == EXPECTED_VERSION
    assert list(versions)[-1] == EXPECTED_VERSION
    assert versions[EXPECTED_VERSION] == plugin["minAppVersion"]
