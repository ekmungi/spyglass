"""Settings REST API: read + edit the dashboard-editable settings.

Edits persist to the data-dir overlay and apply to the running service where
possible; the port needs a restart, which the dashboard notes in the UI.
Note paths serialize vault-root-relative when they live under the vault.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from spyglass_service.config import Settings, save_overlay

router = APIRouter(prefix="/api")

_NOTE_KEYS = ("feed_note_path", "interest_note_path", "preferences_note_path")


class SettingsPatch(BaseModel):
    """Any subset of the editable settings; absent fields stay unchanged."""

    vault_path: str | None = None
    feed_note_path: str | None = None
    interest_note_path: str | None = None
    preferences_note_path: str | None = None
    port: int | None = None
    fulltext_refresh_hours: float | None = None
    relevance_threshold: Literal["high", "medium", "low", "out"] | None = None
    relevance_model: Literal["haiku", "sonnet"] | None = None
    # yt-transcribe CLI path for video transcripts; "" means auto-discover.
    yt_transcribe_cmd: str | None = None
    # Model behind the in-reader chat pane. Editable here until a proper Models picker
    # ships -- an OpenRouter model id, so no Literal to keep it from going stale.
    chat_model: str | None = None
    # The Slack channel for the paper inbox, without the leading '#'.
    inbox_channel: str | None = None
    # Background jobs: the Claude Code command ("" finds it), the time limit per run, and
    # the vault folder for detailed notes.
    claude_command: str | None = None
    job_timeout_minutes: int | None = Field(default=None, ge=1, le=120)
    detail_notes_subdir: str | None = Field(default=None, min_length=1)
    # The Obsidian MCP server filing runs move notes with, and the address that answers while
    # Obsidian runs (the Local REST API: http on 27123, or https on 27124).
    obsidian_mcp_server: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    # The model each background job runs on: an alias or a full model name.
    job_model_prepare: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\[\]-]+$")
    job_model_file: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\[\]-]+$")
    obsidian_probe_url: str | None = Field(
        default=None, pattern=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?(/.*)?$")

    @field_validator("detail_notes_subdir")
    @classmethod
    def _inside_the_vault(cls, value: str | None) -> str | None:
        """A folder inside the vault: relative, without "..", so notes never land outside it."""
        if value is None:
            return value
        clean = value.strip().replace("\\", "/").strip("/")
        absolute = value.strip().startswith(("/", "\\")) or bool(PureWindowsPath(value).drive)
        if not clean or absolute or ".." in PurePosixPath(clean).parts:
            raise ValueError("use a folder inside the vault, like 03 RESOURCES/Spyglass/Brief notes")
        return clean


def _display_path(value: Path | None, vault: Path | None) -> str | None:
    """Show a note path vault-root-relative when it lives under the vault."""
    if value is None:
        return None
    if vault is not None:
        try:
            return value.relative_to(vault).as_posix()
        except ValueError:
            pass
    return str(value)


def _serialize(settings: Settings) -> dict:
    """The editable subset the Settings tab renders."""
    vault = settings.vault_path
    return {
        "vault_path": str(vault) if vault else None,
        "feed_note_path": _display_path(settings.feed_note_path, vault),
        "interest_note_path": _display_path(settings.interest_note_path, vault),
        "preferences_note_path": _display_path(settings.preferences_note_path, vault),
        "port": settings.port,
        "fulltext_refresh_hours": settings.fulltext_refresh_hours,
        "relevance_threshold": settings.relevance_threshold,
        "relevance_model": settings.relevance_model,
        "yt_transcribe_cmd": settings.yt_transcribe_cmd,
        "chat_model": settings.chat_model,
        "inbox_channel": settings.inbox_channel,
        "claude_command": settings.claude_command,
        "job_timeout_minutes": settings.job_timeout_minutes,
        "detail_notes_subdir": settings.detail_notes_subdir,
        "obsidian_mcp_server": settings.obsidian_mcp_server,
        "obsidian_probe_url": settings.obsidian_probe_url,
        "job_model_prepare": settings.job_model_prepare,
        "job_model_file": settings.job_model_file,
        "engine": settings.engine,
    }


@router.get("/settings")
def get_settings(request: Request) -> dict:
    """Current editable settings for the Settings tab."""
    return _serialize(request.app.state.settings)


@router.patch("/settings")
def patch_settings(request: Request, body: SettingsPatch) -> dict:
    """Apply and persist edited settings; relative note paths resolve in the vault."""
    settings: Settings = request.app.state.settings
    updates = body.model_dump(exclude_none=True)
    vault = Path(updates["vault_path"]) if updates.get("vault_path") else settings.vault_path
    for key in _NOTE_KEYS:
        if key in updates and vault is not None and not Path(updates[key]).is_absolute():
            updates[key] = str(vault / updates[key])
    if updates.get("claude_command") == "":
        updates["claude_command"] = None
    save_overlay(settings, updates)
    for key, value in updates.items():
        setattr(settings, key, Path(value) if key.endswith("_path") and value else value)
    # Re-resolve the yt-transcribe CLI live so a path change takes effect without a restart
    # (explicit value, or auto-discovery when cleared).
    if "yt_transcribe_cmd" in updates:
        from spyglass_service.documents import set_yt_transcribe_cmd
        from spyglass_service.yt_discovery import discover_yt_transcribe

        set_yt_transcribe_cmd(
            settings.yt_transcribe_cmd or discover_yt_transcribe(settings.vault_path)
        )
    return _serialize(settings)
