"""Write the list of program files the Spyglass MSI installs, as a WiX source file.

    python installer/harvest.py --out installer/obj/files.wxs

installer/spyglass.wxs names the few files it needs by Id (the launcher, the helper, uv); this
script lists the rest: the service's source, the built interface, the browser extension and the
bundled skills, the same folders the old installer copied. Each folder becomes one component
whose key path is a per-user registry value, so repair works in a user's profile, with a
RemoveFolder entry so an uninstall leaves no empty folders behind. Ids and component GUIDs are
derived from the folder and file paths, so the same tree always gives the same output.
It uses only the standard library: the release workflow runs it before uv exists.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from pathlib import Path
from xml.sax.saxutils import quoteattr

# (folder in the repository, folder in the install folder): what the program needs at run time.
SOURCES = (("src", "src"), ("frontend/dist", "frontend/dist"),
           ("browser-extension", "browser-extension"), ("skills", "skills"))
# Left out wherever they appear: caches and packages that only development uses.
EXCLUDED_NAMES = frozenset({"__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"})
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})
# Left out at the top of one source folder only: the extension's own tests and build tools.
EXCLUDED_TOP = {"browser-extension": frozenset({"tests", "tools"})}
# Component GUIDs are UUIDv5 names in this namespace, so a folder keeps its GUID across builds.
GUID_NAMESPACE = uuid.UUID("4C91870A-6F3B-4C3B-8F6D-BD1ECD6D7338")
# Where each component's key path value lives; uninstall removes the whole Spyglass key.
COMPONENTS_KEY = r"Software\ekmungi\Spyglass\Components"
WXS_NAMESPACE = "http://wixtoolset.org/schemas/v4/wxs"


def _excluded(relative: Path, top: str) -> bool:
    """Whether a path inside source folder `top` is left out."""
    parts = relative.parts
    if any(part in EXCLUDED_NAMES for part in parts) or relative.suffix in EXCLUDED_SUFFIXES:
        return True
    return bool(parts) and parts[0] in EXCLUDED_TOP.get(top, frozenset())


def collect(root: Path) -> dict[str, list[Path]]:
    """Map each install folder (forward slashes, relative to the install folder) to its files.

    Every folder on the way down is listed, even one that holds only folders, so each gets a
    component that removes it on uninstall. Files are sorted for stable output.
    """
    folders: dict[str, list[Path]] = {}
    for source, target in SOURCES:
        base = root / source
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(base)
            if _excluded(relative, source) or not path.is_file():
                continue
            folder = "/".join([target, *relative.parent.parts]) if relative.parent.parts else target
            folders.setdefault(folder, []).append(path)
            parts = folder.split("/")
            for depth in range(1, len(parts)):
                folders.setdefault("/".join(parts[:depth]), [])
    return dict(sorted(folders.items()))


def _ident(prefix: str, text: str) -> str:
    """A WiX Id for `text`: the prefix and a short hash, within the 72-character limit."""
    return prefix + hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:24]


def _wix_text(text: str) -> str:
    """Escape WiX's own variable markers, then quote for XML."""
    return quoteattr(text.replace("$(", "$$(").replace("!(", "!!("))


def _directory_xml(folder: str, children: dict[str, dict], indent: str) -> list[str]:
    """Nested Directory elements for `folder` and everything below it."""
    name = folder.rsplit("/", 1)[-1]
    lines = [f"{indent}<Directory Id={quoteattr(_ident('d', folder))} Name={_wix_text(name)}>"]
    for child in sorted(children):
        lines += _directory_xml(f"{folder}/{child}", children[child], indent + "  ")
    lines.append(f"{indent}</Directory>")
    return lines


def _tree(folders: dict[str, list[Path]]) -> dict[str, dict]:
    """The folder paths as a nested dictionary, top folders first."""
    tree: dict[str, dict] = {}
    for folder in folders:
        node = tree
        for part in folder.split("/"):
            node = node.setdefault(part, {})
    return tree


def _component_xml(folder: str, files: list[Path], root: Path) -> list[str]:
    """One component: the folder's files, its registry key path and its RemoveFolder entry."""
    directory = _ident("d", folder)
    component = _ident("c", folder)
    guid = str(uuid.uuid5(GUID_NAMESPACE, folder.lower())).upper()
    lines = [f"    <Component Id={quoteattr(component)} Directory={quoteattr(directory)} "
             f"Guid={quoteattr(guid)}>",
             f"      <RegistryValue Root=\"HKCU\" Key={quoteattr(COMPONENTS_KEY)} "
             f"Name={quoteattr(component)} Type=\"integer\" Value=\"1\" KeyPath=\"yes\" />",
             f"      <RemoveFolder Id={quoteattr(_ident('r', folder))} "
             f"Directory={quoteattr(directory)} On=\"uninstall\" />"]
    for path in files:
        source = str(path.relative_to(root)).replace("/", "\\")
        lines.append(f"      <File Id={quoteattr(_ident('f', source))} Source={_wix_text(source)} />")
    lines.append("    </Component>")
    return lines


def render(folders: dict[str, list[Path]], root: Path) -> str:
    """The WiX source: the folder tree under INSTALLFOLDER and the ProgramFiles component group.

    File sources are written relative to `root`, the folder WiX is run from.
    """
    lines =['<?xml version="1.0" encoding="utf-8"?>',
             "<!-- Written by installer/harvest.py for each build; do not edit. -->",
             f"<Wix xmlns={quoteattr(WXS_NAMESPACE)}>", "  <Fragment>",
             '    <DirectoryRef Id="INSTALLFOLDER">']
    tree = _tree(folders)
    for top in sorted(tree):
        lines += _directory_xml(top, tree[top], "      ")
    lines += ["    </DirectoryRef>", "  </Fragment>", "  <Fragment>",
              '    <ComponentGroup Id="ProgramFiles">']
    for folder, files in folders.items():
        lines += ["  " + line for line in _component_xml(folder, files, root)]
    lines += ["    </ComponentGroup>", "  </Fragment>", "</Wix>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Harvest the repository at --root (default: this script's parent's parent) into --out."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    folders = collect(args.root)
    if "src/spyglass_service" not in folders:
        print(f"No src/spyglass_service under {args.root}", file=sys.stderr)
        return 1
    if "frontend/dist" not in folders:
        print("Build the interface first: npm run build in frontend", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(folders, args.root), encoding="utf-8")
    count = sum(len(files) for files in folders.values())
    print(f"Wrote {args.out}: {count} files in {len(folders)} folders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
