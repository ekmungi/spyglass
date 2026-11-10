"""Checking the folder a filing run picked.

A filing run only names a folder. Before Spyglass moves the note there, the folder must be a real
one inside the vault, not hidden, and not one of Spyglass's own folders, which hold its output and
not the user's knowledge.
"""

import re
from pathlib import Path

from spyglass_service.config import Settings
from spyglass_service.detail_notes import folder_names, in_spyglass_folder, is_inside

# Characters Windows refuses in a folder name; a colon also marks a drive ("C:").
_ILLEGAL = re.compile(r'[:*?"<>|\x00-\x1f]')


def folder_parts(folder: str) -> list[str]:
    """The names in a folder path, with / or \\ as separators; empty parts and "." are dropped."""
    return [part.strip() for part in folder.strip().replace("\\", "/").split("/")
            if part.strip() not in ("", ".")]


def check_filing_folder(settings: Settings, folder: str) -> tuple[Path | None, str | None]:
    """The vault folder to file into, as (path, None), or (None, the reason in plain words)."""
    vault = settings.vault_path
    if vault is None:
        return None, "The vault folder is not set."
    parts = folder_parts(folder)
    if not parts:
        return None, "No folder was given. Give a folder in the vault, such as 01 PROJECTS/Name."
    if any(_ILLEGAL.search(part) for part in parts):
        return None, ("Give the folder relative to the vault, such as 01 PROJECTS/Name, without a "
                      "drive letter and without any of these characters: : * ? \" < > |")
    if ".." in parts:
        return None, "A folder cannot use .. to go up. Give it relative to the vault."
    if any(part.startswith(".") for part in parts):
        return None, "Folders that start with a dot, such as .obsidian and .trash, are not allowed."
    wanted = "/".join(parts)
    target = vault.joinpath(*parts)
    if not is_inside(target, vault):
        return None, f"{wanted} is outside the vault."
    # Where the folder leads, not only how it is written: a junction can point at the top.
    if target.resolve() == vault.resolve():
        return None, f"{wanted} leads to the vault's top folder. Choose a folder inside the vault."
    if not target.is_dir():
        return None, f"There is no folder {wanted} in the vault. Choose a folder that exists."
    if in_spyglass_folder(settings, target):
        return None, (f"{wanted} is one of Spyglass's own folders ({folder_names(settings)}), which "
                      "hold Spyglass's output and not your knowledge. Choose a folder in your "
                      "projects, areas or resources.")
    return target, None
