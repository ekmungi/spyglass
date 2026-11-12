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
from spyglass_service.radar.filing_config import (
    BACKGROUND_UNAVAILABLE, background_unlocked, effective_mode,
)

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
    # Radar: when the daily brief is composed (local HH:MM), in which time zone ("" = this
    # machine's), how often collection runs, and the vault folder for saved notes.
    radar_brief_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    radar_timezone: str | None = Field(default=None, max_length=64)
    radar_collect_hours: float | None = Field(default=None, ge=0.25, le=24)
    # Radar models (OpenRouter ids) for judging, digesting and short writing jobs.
    radar_triage_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/\[\]-]+$")
    radar_digest_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/\[\]-]+$")
    radar_writer_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/\[\]-]+$")
    # Privacy switches: taste examples sent to the judging model, images fetched through the
    # service, and the outside page-rendering service for sites that block direct reading.
    privacy_send_examples: bool | None = None
    privacy_proxy_images: bool | None = None
    privacy_allow_bot_checks: bool | None = None
    jina_enabled: bool | None = None
    # Fallback order for bulk judging, capture check interval, and how long unread text is kept.
    radar_llm_fallback: str | None = Field(default=None, pattern=r"^[a-z_, ]{0,80}$")
    radar_capture_poll_seconds: int | None = Field(default=None, ge=15, le=3600)
    radar_retention_days: int | None = Field(default=None, ge=0, le=3650)
    # FDA device decisions for the watch list: on or off, plus optional product codes and keywords
    # (comma-separated; letters, digits, spaces and a few marks only, so they stay plain search text).
    radar_fda_enabled: bool | None = None
    radar_fda_product_codes: str | None = Field(default=None, max_length=200,
                                                pattern=r"^[A-Za-z0-9, ]*$")
    radar_fda_keywords: str | None = Field(default=None, max_length=400,
                                           pattern=r"^[A-Za-z0-9 ,.'/&()-]*$")
    # Who does the bulk judging, and the models used on the Claude Code route.
    radar_llm_provider: Literal["openrouter", "claude_code", "gemini", "antigravity"] | None = None
    radar_antigravity_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\[\]-]{0,80}$")
    radar_claude_triage_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\[\]-]+$")
    radar_claude_digest_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\[\]-]+$")
    radar_claude_writer_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._\[\]-]+$")
    # Where the reader's own links arrive from: the Gmail address and labels, the Slack channel.
    gmail_address: str | None = Field(default=None, max_length=254)
    gmail_newsletter_label: str | None = Field(default=None, min_length=1, max_length=100)
    gmail_capture_label: str | None = Field(default=None, min_length=1, max_length=100)
    slack_capture_channel: str | None = Field(default=None, max_length=40)
    # The assistant's default engine and model; "" picks the first available.
    assist_default_engine: str | None = Field(default=None, max_length=80)
    assist_default_model: str | None = Field(default=None, max_length=120)
    # Background filing: the mode, the quiet period before a run, the daily safety time and the
    # model the hidden Claude Code session uses (an alias such as "sonnet" or a full name).
    radar_filing_mode: Literal["off", "auto", "plan_first"] | None = None
    radar_filing_quiet_minutes: int | None = Field(default=None, ge=2, le=240)
    radar_filing_daily_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    radar_filing_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\[\]-]{0,79}$")

    @field_validator("radar_timezone")
    @classmethod
    def _known_time_zone(cls, value: str | None) -> str | None:
        """An IANA zone name the machine knows, or empty for the machine's own zone."""
        if not value:
            return value
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("use a time zone name like Europe/Amsterdam") from exc
        return value

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

    @field_validator("radar_filing_mode")
    @classmethod
    def _background_is_locked(cls, value: str | None) -> str | None:
        """Only "off" can be stored while background filing is locked in this version."""
        if value not in (None, "off") and not background_unlocked():
            raise ValueError(BACKGROUND_UNAVAILABLE)
        return value


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
        "radar_brief_time": settings.radar_brief_time,
        "radar_timezone": settings.radar_timezone,
        "radar_collect_hours": settings.radar_collect_hours,
        "radar_triage_model": settings.radar_triage_model,
        "radar_digest_model": settings.radar_digest_model,
        "radar_writer_model": settings.radar_writer_model,
        "gmail_address": settings.gmail_address,
        "gmail_newsletter_label": settings.gmail_newsletter_label,
        "gmail_capture_label": settings.gmail_capture_label,
        "slack_capture_channel": settings.slack_capture_channel,
        "assist_default_engine": settings.assist_default_engine,
        "assist_default_model": settings.assist_default_model,
        "privacy_send_examples": settings.privacy_send_examples,
        "privacy_proxy_images": settings.privacy_proxy_images,
        "privacy_allow_bot_checks": settings.privacy_allow_bot_checks,
        "jina_enabled": settings.jina_enabled,
        "radar_llm_provider": settings.radar_llm_provider,
        "radar_antigravity_model": settings.radar_antigravity_model,
        "radar_llm_fallback": settings.radar_llm_fallback,
        "radar_capture_poll_seconds": settings.radar_capture_poll_seconds,
        "radar_retention_days": settings.radar_retention_days,
        "radar_fda_enabled": settings.radar_fda_enabled,
        "radar_fda_product_codes": settings.radar_fda_product_codes,
        "radar_fda_keywords": settings.radar_fda_keywords,
        "radar_claude_triage_model": settings.radar_claude_triage_model,
        "radar_claude_digest_model": settings.radar_claude_digest_model,
        "radar_claude_writer_model": settings.radar_claude_writer_model,
        "radar_filing_mode": effective_mode(settings),
        "radar_filing_quiet_minutes": settings.radar_filing_quiet_minutes,
        "radar_filing_daily_time": settings.radar_filing_daily_time,
        "radar_filing_model": settings.radar_filing_model,
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
