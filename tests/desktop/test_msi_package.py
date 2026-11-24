"""The WiX source of the per-user Windows Installer package, and the file list harvested into it.

WiX itself runs only in the release workflow, so these tests read the XML and check what an
install depends on: the per-user scope, the Start-menu entry's app ID (without it Windows lists a
new app only after the next sign-in), the feature tree and the registry values setup's own steps
read, and when each custom action runs.
"""

import importlib.util
import re
import xml.etree.ElementTree as ET  # Element types only; parsing goes through defusedxml
from pathlib import Path

import pytest
from defusedxml.ElementTree import fromstring, parse

from spyglass_service.desktop.setup_steps import BROWSER_IDS, FEATURES_KEY

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "installer" / "spyglass.wxs"
BUNDLE = ROOT / "installer" / "bundle.wxs"
NS = {"w": "http://wixtoolset.org/schemas/v4/wxs",
      "bal": "http://wixtoolset.org/schemas/v4/wxs/bal"}
W = "{http://wixtoolset.org/schemas/v4/wxs}"


def _load_harvest():
    spec = importlib.util.spec_from_file_location("harvest", ROOT / "installer" / "harvest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def package() -> ET.Element:
    return parse(PACKAGE).getroot().find("w:Package", NS)


def _by_id(root: ET.Element, tag: str, ident: str) -> ET.Element:
    found = root.find(f".//w:{tag}[@Id='{ident}']", NS)
    assert found is not None, f"no {tag} {ident}"
    return found


def test_package_is_per_user_with_a_fixed_upgrade_code(package: ET.Element) -> None:
    assert package.get("Scope") == "perUser"
    assert package.get("Name") == "Spyglass" and package.get("Manufacturer") == "ekmungi"
    assert package.get("Version") == "$(var.Version)"
    assert package.get("UpgradeCode") == "2B3EE94C-873E-4560-9FAC-5A44D08C7F29"
    assert package.find("w:MajorUpgrade", NS) is not None


def test_installs_into_the_folder_the_old_installer_used(package: ET.Element) -> None:
    local = package.find("w:StandardDirectory[@Id='LocalAppDataFolder']", NS)
    programs = local.find("w:Directory[@Name='Programs']", NS)
    assert programs.find("w:Directory[@Id='INSTALLFOLDER']", NS).get("Name") == "Spyglass"


def test_start_menu_entry_carries_the_app_id(package: ET.Element) -> None:
    menu = package.find("w:StandardDirectory[@Id='ProgramMenuFolder']", NS)
    shortcut = menu.find(".//w:Shortcut", NS)
    assert shortcut.get("Name") == "Spyglass"
    assert shortcut.get("Target") == "[INSTALLFOLDER]Spyglass.exe"
    prop = shortcut.find("w:ShortcutProperty", NS)
    assert (prop.get("Key"), prop.get("Value")) == ("System.AppUserModel.ID", "ekmungi.Spyglass")


def test_every_component_has_a_per_user_registry_key_path(package: ET.Element) -> None:
    """A file key path in a user's profile breaks repair; the probe that worked used registry."""
    for component in package.iter(f"{W}Component"):
        keys = [e for e in component if e.get("KeyPath") == "yes"]
        assert len(keys) == 1 and keys[0].tag == f"{W}RegistryValue", component.get("Id")
        assert keys[0].get("Root") == "HKCU"


def test_program_files_include_the_launcher_helper_uv_and_tray_icon(package: ET.Element) -> None:
    sources = {f.get("Source") for f in package.iter(f"{W}File")}
    assert {r"installer\Spyglass.exe", r"installer\SpyglassSetup.exe", r"installer\uv.exe",
            "pyproject.toml", "uv.lock", r"installer\spyglass.ico"} <= sources
    icon = _by_id(package, "File", "TrayIcon")
    assert package.find(".//w:Directory[@Name='installer']", NS) is not None
    assert icon.get("Source") == r"installer\spyglass.ico"


def _feature_value(package: ET.Element, feature_id: str) -> str:
    """The Features value name the feature's component writes."""
    feature = _by_id(package, "Feature", feature_id)
    ref = feature.find("w:ComponentRef", NS).get("Id")
    value = _by_id(package, "Component", ref).find("w:RegistryValue", NS)
    assert value.get("Key") == FEATURES_KEY
    return value.get("Name")


@pytest.mark.parametrize(("feature", "value", "level"), [
    ("Autostart", "autostart", "1000"), ("ClaudeConnector", "connector", "1000"),
    ("YouTube", "youtube", "1000"), ("PdfReading", "pdf", "1"), ("LocalAi", "local-ai", "1")])
def test_each_choice_writes_the_value_setup_reads(package, feature, value, level) -> None:
    """Level 1 is ticked by default and 1000 unticked (the install level is 1)."""
    assert _feature_value(package, feature) == value
    assert _by_id(package, "Feature", feature).get("Level") == level


def test_start_with_windows_stays_on_when_it_was_on(package: ET.Element) -> None:
    level = _by_id(package, "Feature", "Autostart").find("w:Level", NS)
    assert (level.get("Value"), level.get("Condition")) == ("1", "AUTOSTART_FOUND")
    search = _by_id(package, "Property", "AUTOSTART_FOUND").find("w:RegistrySearch", NS)
    assert search.get("Key") == r"Software\Microsoft\Windows\CurrentVersion\Run"
    assert search.get("Name") == "Spyglass"


def test_one_browser_choice_per_supported_browser_shown_only_when_found(package) -> None:
    for browser in BROWSER_IDS:
        feature_id = f"Browser{browser.capitalize()}"
        assert _feature_value(package, feature_id) == f"browser.{browser}"
        hidden = _by_id(package, "Feature", feature_id).find("w:Level", NS)
        assert hidden.get("Value") == "0"
        assert hidden.get("Condition") == f"NOT {browser.upper()}_FOUND"
        assert _by_id(package, "Property", f"{browser.upper()}_FOUND").find(
            "w:DirectorySearch", NS) is not None


def test_the_program_itself_cannot_be_left_out(package: ET.Element) -> None:
    core = _by_id(package, "Feature", "Spyglass")
    assert core.get("AllowAbsent") == "no" and core.get("Level") == "1"


def _scheduled(package: ET.Element, action: str) -> ET.Element:
    found = package.find(f"w:InstallExecuteSequence/w:Custom[@Action='{action}']", NS)
    assert found is not None, action
    return found


def test_prepare_runs_before_costing_and_never_on_uninstall_or_upgrade_removal(package) -> None:
    """Removing the old Inno install changes the files on disk, so it must come before costing."""
    action = _by_id(package, "CustomAction", "PrepareSpyglass")
    assert action.get("Execute") == "immediate" and action.get("Return") == "check"
    assert action.get("BinaryRef") == "SetupHelperBinary"
    assert action.get("ExeCommand").startswith('prepare --install-dir "[INSTALLFOLDER]."')
    scheduled = _scheduled(package, "PrepareSpyglass")
    assert scheduled.get("Before") == "CostInitialize"
    assert "NOT UPGRADINGPRODUCTCODE" in scheduled.get("Condition")
    assert 'NOT (REMOVE~="ALL")' in scheduled.get("Condition")


def test_python_is_prepared_after_the_feature_values_are_written(package) -> None:
    build = _by_id(package, "CustomAction", "BuildEnvironment")
    assert (build.get("Execute"), build.get("Return"), build.get("FileRef")) == (
        "deferred", "check", "SetupHelperExe")
    assert _scheduled(package, "BuildEnvironment").get("After") == "WriteRegistryValues"
    rollback = _by_id(package, "CustomAction", "RollbackEnvironment")
    assert rollback.get("Execute") == "rollback"
    assert rollback.get("ExeCommand").startswith("remove-environment ")
    assert _scheduled(package, "RollbackEnvironment").get("Before") == "BuildEnvironment"


def test_uninstall_cleans_up_except_when_a_newer_version_replaces_this_one(package) -> None:
    action = _by_id(package, "CustomAction", "UninstallSpyglass")
    assert action.get("Execute") == "deferred"
    scheduled = _scheduled(package, "UninstallSpyglass")
    assert scheduled.get("Before") == "RemoveFiles"
    assert scheduled.get("Condition") == 'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE'


def test_every_helper_call_passes_the_folder_safely_quoted(package) -> None:
    """A path ending in a backslash would escape the closing quote; the dot prevents that."""
    for action in package.iter(f"{W}CustomAction"):
        command = action.get("ExeCommand")
        if command is not None:
            assert '"[INSTALLFOLDER]."' in command, action.get("Id")


def test_the_last_page_offers_to_open_spyglass(package: ET.Element) -> None:
    publish = package.find("w:UI/w:Publish[@Dialog='ExitDialog']", NS)
    assert publish.get("Value") == "LaunchSpyglass"
    assert "NOT Installed" in publish.get("Condition")
    assert _by_id(package, "Property", "WIXUI_EXITDIALOGOPTIONALCHECKBOX").get("Value") == "1"


def test_bundle_wraps_the_package_and_shows_its_choices() -> None:
    bundle = parse(BUNDLE).getroot().find("w:Bundle", NS)
    assert bundle.get("UpgradeCode") != "2B3EE94C-873E-4560-9FAC-5A44D08C7F29"
    package = bundle.find("w:Chain/w:MsiPackage", NS)
    assert package.get("SourceFile") == "$(var.MsiPath)"
    assert package.get(f"{{{NS['bal']}}}DisplayInternalUICondition") == "1"


def test_no_vault_record_numbers_in_the_installer_sources() -> None:
    for path in (PACKAGE, BUNDLE, ROOT / "installer" / "harvest.py",
                 ROOT / "installer" / "build_msi.ps1"):
        assert not re.search(r"\b(ISS|SPEC|DEC|F|P|R)-\d{3}\b", path.read_text(encoding="utf-8"))


# ---- the harvested file list ---------------------------------------------------------------


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A small repository: program files, and the things that must stay out."""
    files = ["src/pkg/__init__.py", "src/pkg/sub/mod.py", "src/pkg/__pycache__/mod.cpython-313.pyc",
             "src/pkg/stale.pyc", "frontend/dist/index.html", "frontend/dist/assets/app.js",
             "browser-extension/manifest.json", "browser-extension/tests/t.js",
             "browser-extension/tools/build.js", "browser-extension/node_modules/x/i.js",
             "skills/spyglass/SKILL.md", "src/pkg/odd $(name).txt"]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return tmp_path


def test_harvest_lists_program_files_and_leaves_out_caches_and_tests(tree: Path) -> None:
    harvest = _load_harvest()
    folders = harvest.collect(tree)
    flat = {f"{folder}/{name.name}" for folder, names in folders.items() for name in names}
    assert {"src/pkg/__init__.py", "src/pkg/sub/mod.py", "frontend/dist/assets/app.js",
            "browser-extension/manifest.json", "skills/spyglass/SKILL.md"} <= flat
    assert not any("__pycache__" in f or f.endswith(".pyc") or "/tests/" in f or "/tools/" in f
                   or "node_modules" in f for f in flat)
    assert "frontend" in folders  # a folder with only folders in it still gets removed


def test_harvest_writes_one_component_per_folder_with_stable_ids(tree: Path) -> None:
    harvest = _load_harvest()
    first = harvest.render(harvest.collect(tree), tree)
    assert first == harvest.render(harvest.collect(tree), tree)
    root = fromstring(first)
    components = list(root.iter(f"{W}Component"))
    assert len(components) == len(harvest.collect(tree))
    for component in components:
        assert component.find("w:RemoveFolder", NS).get("On") == "uninstall"
        key = component.find("w:RegistryValue", NS)
        assert key.get("KeyPath") == "yes" and key.get("Root") == "HKCU"
        assert re.fullmatch(r"[0-9A-F-]{36}", component.get("Guid"))
    sources = [f.get("Source") for f in root.iter(f"{W}File")]
    assert r"src\pkg\sub\mod.py" in sources
    # WiX would read "$(" as a variable; the harvest doubles the dollar sign.
    assert r"src\pkg\odd $$(name).txt" in sources


def test_harvest_of_the_repository_includes_the_service() -> None:
    harvest = _load_harvest()
    folders = harvest.collect(ROOT)
    assert any(p.name == "__init__.py" for p in folders["src/spyglass_service"])
    assert "skills" in folders or any(k.startswith("skills/") for k in folders)
