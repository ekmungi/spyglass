"""Whether filing into a notes vault is set up, and which vault skills Spyglass names.

The vault skills are configuration, never code: the owner sets the plugin that holds them and the
full names of the two skills in the local environment file (`SPYGLASS_RADAR_FILING_PLUGIN`,
`SPYGLASS_RADAR_FILING_INGEST_SKILL`, `SPYGLASS_RADAR_FILING_MANAGE_SKILL`). Filing is
"configured" only with a vault folder and both skill names set; otherwise the interface hides the
feature, queuing is refused, no background run starts and the visible session is not offered.

Three more values are environment-only (read straight from the process environment, never from the
saved settings, so no screen or stored value can change them):
- `SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED`: a developer's unlock. Without it no background run
  starts in this version, whatever mode is stored.
- `SPYGLASS_RADAR_FILING_TOOL`: the file name of the vault tool's launcher (empty by default).
- `SPYGLASS_RADAR_FILING_TOOL_COMMANDS`: the comma-separated look-up commands of that tool a run
  may use (empty by default). Both are validated strictly; a malformed value counts as unset.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "Filing into a notes vault is not set up on this Spyglass."
SKILLS_NOT_CONFIGURED = "The vault's filing skills are not configured."
# Why no background run starts in this version, and the line the "To file" view shows instead.
BACKGROUND_UNAVAILABLE = "Background filing is not available in this version."
BACKGROUND_UNAVAILABLE_LINE = f"{BACKGROUND_UNAVAILABLE} Use File now."
UNLOCK_ENV = "SPYGLASS_RADAR_FILING_BACKGROUND_UNLOCKED"
TOOL_ENV = "SPYGLASS_RADAR_FILING_TOOL"
TOOL_COMMANDS_ENV = "SPYGLASS_RADAR_FILING_TOOL_COMMANDS"
_TRUE = ("1", "true", "yes", "on")
# A launcher's file name: letters, digits, dot, hyphen and underscore; never only dots.
_TOOL_NAME = re.compile(r"(?=.*[A-Za-z0-9_-])[A-Za-z0-9._-]{1,64}")
# A look-up command: lowercase words (digits and hyphens inside a word) with single spaces.
_COMMAND = re.compile(r"[a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*){0,3}")
COMMANDS_MAX = 20
# A skill's full name: letters, digits, hyphens and underscores, with at most one colon between
# the plugin's name and the skill's (for example "vault-skills:ingest").
_SKILL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}(?::[A-Za-z0-9_-]{1,64})?")


def valid_skill_name(value: object) -> str | None:
    """`value` stripped when it has the shape of a skill name, else None."""
    text = value.strip() if isinstance(value, str) else ""
    return text if _SKILL_NAME.fullmatch(text) else None


def skill_names(settings: object) -> dict[str, str | None]:
    """{"ingest", "manage"}: the configured skill names, or None for an unset or malformed one."""
    return {"ingest": valid_skill_name(getattr(settings, "radar_filing_ingest_skill", "")),
            "manage": valid_skill_name(getattr(settings, "radar_filing_manage_skill", ""))}


def skills_configured(settings: object) -> bool:
    """True when both vault skill names are set and well formed."""
    return all(skill_names(settings).values())


def filing_configured(settings: object) -> bool:
    """True only with a vault folder set and both vault skill names configured."""
    return bool(getattr(settings, "vault_path", None)) and skills_configured(settings)


def background_unlocked() -> bool:
    """True only when the developer unlock is set in the environment (default: not available)."""
    return os.environ.get(UNLOCK_ENV, "").strip().lower() in _TRUE


def effective_mode(settings: object) -> str:
    """The stored filing mode, or "off" while background filing is locked in this version."""
    mode = str(getattr(settings, "radar_filing_mode", "off") or "off")
    return mode if background_unlocked() else "off"


def tool_name() -> str:
    """The vault tool's launcher file name from the environment; "" when unset or malformed."""
    text = os.environ.get(TOOL_ENV, "").strip()
    if text and not _TOOL_NAME.fullmatch(text):
        logger.warning("%s is not a plain file name; ignored", TOOL_ENV)
        return ""
    return text


def tool_commands() -> tuple[str, ...]:
    """The allowed look-up commands from the environment, or () when unset.

    Fails closed: one malformed entry (or too many) makes the whole list empty, so a typo never
    widens what a run may type into the shell.
    """
    parts = [p.strip() for p in os.environ.get(TOOL_COMMANDS_ENV, "").split(",") if p.strip()]
    if len(parts) > COMMANDS_MAX or not all(_COMMAND.fullmatch(p) for p in parts):
        if parts:
            logger.warning("%s holds a malformed entry; no look-up commands are allowed",
                           TOOL_COMMANDS_ENV)
        return ()
    return tuple(dict.fromkeys(parts))
