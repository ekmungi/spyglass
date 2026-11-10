"""Service configuration: localhost binding, data locations, vault path.

All values can be overridden with SPYGLASS_-prefixed environment variables.
Settings edited in the dashboard persist as an overlay JSON in the data dir
and are re-applied over the env config on every startup.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# Settings the dashboard may edit; everything else stays env-only.
OVERLAY_KEYS = (
    "vault_path", "feed_note_path", "interest_note_path", "preferences_note_path",
    "port", "fulltext_refresh_hours", "relevance_threshold", "relevance_model",
    "enrich_model", "relevance_gate", "yt_transcribe_cmd", "brief_horizon_days",
    "jina_enabled", "browser_enabled", "chat_model", "inbox_channel",
    "claude_command", "job_timeout_minutes", "detail_notes_subdir", "obsidian_mcp_server",
    "obsidian_probe_url", "job_model_prepare", "job_model_file",
)


def _default_data_dir() -> Path:
    """Operational-state home: ~/.spyglass.

    A single local, non-synced folder the plugin owns and can override via SPYGLASS_DATA_DIR.
    Kept out of a cloud-synced vault folder on purpose: a live SQLite DB in a cloud-synced
    folder is a corruption vector.
    """
    return Path.home() / ".spyglass"


class Settings(BaseSettings):
    """Runtime settings for the Spyglass service.

    Defaults bind localhost only; the vault path has no default because writing
    into the wrong vault would be worse than failing fast.
    """

    model_config = SettingsConfigDict(env_prefix="SPYGLASS_", env_file=".env")

    host: str = "127.0.0.1"
    port: int = 7777
    # Host header values the service answers (any port). A web page can point its own domain at
    # 127.0.0.1 and then read the replies, but its requests still name that domain, so only this
    # computer's own names are allowed. Deliberately not a dashboard-editable setting.
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    data_dir: Path = _default_data_dir()
    vault_path: Path | None = None
    # Vault note listing RSS subscriptions; editable from any device.
    feed_note_path: Path | None = None
    # Raindrop personal test token; absent means Raindrop is disabled.
    raindrop_token: str | None = None
    # A successful run older than this counts as stale (run-on-open-if-stale).
    stale_hours: float = 6.0
    # Hours between automatic full-text re-fetches for kept items.
    fulltext_refresh_hours: float = 24.0
    # Default relevance floor for the dashboard view: high/medium/low/out.
    relevance_threshold: str = "medium"
    # Model for the relevance + preference-learning passes: haiku/sonnet.
    relevance_model: str = "haiku"
    # OpenRouter API key for the enrichment pipeline. Read from OPENROUTER_API_KEY
    # too (not just SPYGLASS_-prefixed) so it reuses an existing OpenRouter key. Never
    # logged; never written to the overlay.
    openrouter_api_key: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"))
    # OpenRouter model for enrichment; configurable.
    enrich_model: str = "deepseek/deepseek-v4-flash"
    # Model behind the in-reader chat pane. TEMPORARY DEFAULT: the same model
    # the enrichment pipeline already uses -- the key is configured, it streams free-form text,
    # it is cheap enough for conversational use, and its window is large enough that the
    # context budget has headroom. It is a SETTING, not a hardcode: it is in OVERLAY_KEYS, so
    # it is editable through /api/settings today.
    # Revisit the default when Settings -> Models lands.
    chat_model: str = "deepseek/deepseek-v4-flash"
    # Gate-1 relevance cutoff (0-100): items scoring below this are not fetched/summarized.
    relevance_gate: int = 40
    # Embedder selector; only "arctic" implemented.
    embedder: str = "arctic"
    # yt-transcribe CLI path/command for video transcripts. Empty = auto-discover (the
    # YouTube Transcribe plugin's config -> PATH -> known install locations). Reads the plain
    # SPYGLASS_YT_TRANSCRIBE_CMD env var too.
    yt_transcribe_cmd: str = ""
    # Keep the spyglass server in the vault's .mcp.json so Claude desktop sessions opened in the
    # vault find it. SPYGLASS_REGISTER_MCP=false leaves the file to the user.
    register_mcp: bool = True
    # No longer used (the terminal launcher no longer exists); kept so an old .env that sets
    # SPYGLASS_SPAWN_AUTO still loads.
    spawn_auto: bool | None = None
    # The Slack channel the user drops papers into for the inbox, e.g. "paper-inbox".
    inbox_channel: str = ""
    # Who does Spyglass's AI work. Only "claude" exists today: conversations in the
    # linked Claude desktop session, jobs in Claude. Job instructions are served through MCP
    # (get_instructions), so another engine can be added without changing them.
    engine: Literal["claude"] = "claude"
    # Background jobs: the Claude Code command Spyglass runs hidden, and how long one run
    # may take. None finds `claude` on PATH, then in ~/.local/bin (the native installer's home).
    claude_command: str | None = None
    job_timeout_minutes: int = 10
    # The model each job runs on: Claude Code's own default on a Max plan is Opus,
    # which uses the shared limits fastest. Sonnet writes detailed notes; Haiku picks a folder.
    # Aliases (haiku, sonnet, opus, fable) or full model names.
    job_model_prepare: str = "sonnet"
    job_model_file: str = "haiku"
    # Where detailed notes are written, one folder per day.
    detail_notes_subdir: str = "03 RESOURCES/Spyglass/Brief notes"
    # The Obsidian MCP server a filing job moves notes with: its moves fix links, and comments
    # attached to a note follow a move only while Obsidian runs. Its address answers while
    # Obsidian is open; Spyglass opens Obsidian and waits for it before a filing job.
    obsidian_mcp_server: str = "obsidian-vault"
    obsidian_probe_url: str = "http://127.0.0.1:27123/"
    obsidian_wait_seconds: int = 90
    # Vault note describing the user's interests; read on every curation run.
    interest_note_path: Path | None = None
    # Vault note of LEARNED preferences; read by the relevance + preference skills.
    preferences_note_path: Path | None = None
    # Where briefings land inside the vault (relative subpath).
    briefing_subdir: str = "03 RESOURCES/Research/Spyglass"
    # Where downloaded documents (papers, PDFs) are saved inside the vault.
    documents_subdir: str = "03 RESOURCES/Research/Spyglass/papers"
    # Rotating DB backups: how many timestamped snapshots to retain (the rest are
    # pruned). The DB has no other backup, so this is the only safety net.
    backup_keep: int = 5
    # Recency horizon for Daily Brief eligibility, in days, on the publish-day (local_day)
    # axis. Without a horizon the WHOLE never-briefed backlog is eligible; this bounds
    # eligibility to roughly the last 2 weeks while still letting a resumed outage catch up on
    # everything within that window. 0 or a negative value disables the horizon (unbounded
    # backlog eligibility) -- an explicit escape hatch, not the recommended setting.
    brief_horizon_days: int = 14
    # Enables the T2 Jina Reader acquire rung: when a page is bot-walled past T0/T1,
    # escalate to https://r.jina.ai/ which renders JS server-side and returns clean markdown.
    # ON by default. Privacy note:
    # enabling this sends the FAILING url (not the whole corpus, only pages that reached this
    # rung) to jina.ai for rendering -- turn off if that's unacceptable for a given deployment.
    jina_enabled: bool = True
    # Optional Jina Reader API key: keyless requests work (~20 req/min free tier); a key
    # raises the rate limit. Read from JINA_API_KEY too (not just SPYGLASS_-prefixed),
    # mirroring openrouter_api_key. A secret -- NOT in OVERLAY_KEYS, never logged.
    jina_api_key: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_JINA_API_KEY", "JINA_API_KEY"))
    # Enables the T3 patchright (stealth Playwright) acquire rung: a last-resort local
    # headless Chromium, spun up on demand only for HTML targets that T0-T2 all miss,
    # torn down after. ON by default. ONLY consulted for HTML targets -- build_rungs
    # never includes this rung for a pdf/image ladder, so a PDF/image target never
    # launches a browser regardless of this flag.
    browser_enabled: bool = True

    @property
    def db_path(self) -> Path:
        """Location of the SQLite application database inside the data dir."""
        return self.data_dir / "spyglass.db"

    @property
    def backups_dir(self) -> Path:
        """Folder holding rotating timestamped DB snapshots, next to the database."""
        return self.data_dir / "backups"

    @property
    def models_dir(self) -> Path:
        """FastEmbed model cache home inside the data dir, so the one-time
        arctic-embed-s download lands in ~/.spyglass/models, not system temp."""
        return self.data_dir / "models"

    @property
    def overlay_path(self) -> Path:
        """Location of the dashboard-edited settings overlay."""
        return self.data_dir / "settings.json"

    @property
    def effective_preferences_note_path(self) -> Path:
        """Learned-preferences note path used for read/write: the user-configured
        value, or a fixed default next to the DB so the app always maintains the note even
        when no vault note is set. A configured vault path overrides this default."""
        return self.preferences_note_path or (self.data_dir / "preferences.md")


def apply_overlay(settings: Settings) -> Settings:
    """Re-apply dashboard-edited settings stored in the data-dir overlay.

    Returns a new Settings with overlay values layered over the env config;
    a missing or unreadable overlay leaves the settings untouched.
    """
    path = settings.overlay_path
    if not path.is_file():
        return settings
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    updates = {key: stored[key] for key in OVERLAY_KEYS if key in stored}
    return settings.model_copy(update=_coerce_paths(updates)) if updates else settings


def save_overlay(settings: Settings, updates: dict) -> None:
    """Merge updates into the overlay file so edits survive restarts."""
    path = settings.overlay_path
    path.parent.mkdir(parents=True, exist_ok=True)
    stored: dict = {}
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
    stored.update(updates)
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")


def _coerce_paths(updates: dict) -> dict:
    """Turn overlay path strings back into Path objects for the Settings model."""
    coerced = dict(updates)
    for key in ("vault_path", "feed_note_path", "interest_note_path", "preferences_note_path"):
        if coerced.get(key):
            coerced[key] = Path(coerced[key])
    return coerced
