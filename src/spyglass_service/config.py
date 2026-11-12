"""Service configuration: localhost binding, data locations, vault path.

All values can be overridden with SPYGLASS_-prefixed environment variables.
Settings edited in the dashboard persist as an overlay JSON in the data dir
and are re-applied over the env config on every startup.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

logger = logging.getLogger(__name__)

# Keys of settings that no longer exist. A `.env` file written for an older version may still
# hold them; they are dropped with one log line instead of stopping the service at start.
RETIRED_ENV_KEYS = ("SPYGLASS_RADAR_VAULT_SUBDIR",)


def _without_retired(source: PydanticBaseSettingsSource) -> Callable[[], dict[str, Any]]:
    """`source` (the `.env` file) with the retired keys removed, each named once in the log."""
    retired = {key.lower() for key in RETIRED_ENV_KEYS}

    def read() -> dict[str, Any]:
        """The source's values minus the retired keys."""
        values = source()
        for key in [k for k in values if k.lower() in retired]:
            logger.info("Ignoring %s from the .env file: that setting was removed.", key.upper())
        return {k: v for k, v in values.items() if k.lower() not in retired}

    return read

# Settings the dashboard may edit; everything else stays env-only.
OVERLAY_KEYS = (
    "vault_path", "feed_note_path", "interest_note_path", "preferences_note_path",
    "port", "fulltext_refresh_hours", "relevance_threshold", "relevance_model",
    "enrich_model", "relevance_gate", "yt_transcribe_cmd", "brief_horizon_days",
    "jina_enabled", "browser_enabled", "chat_model", "inbox_channel",
    "claude_command", "job_timeout_minutes", "detail_notes_subdir", "obsidian_mcp_server",
    "obsidian_probe_url", "job_model_prepare", "job_model_file",
    "radar_triage_model", "radar_digest_model", "radar_writer_model", "radar_digest_gate",
    "radar_brief_time", "radar_timezone", "radar_collect_hours", "gmail_address",
    "gmail_newsletter_label", "gmail_capture_label", "slack_capture_channel",
    "assist_claude_code_enabled", "assist_codex_cli_enabled",
    "assist_default_engine", "assist_default_model", "radar_llm_provider",
    "assist_antigravity_enabled", "radar_antigravity_model",
    "radar_claude_triage_model", "radar_claude_digest_model", "radar_claude_writer_model",
    "privacy_send_examples", "privacy_proxy_images", "privacy_allow_bot_checks",
    "radar_llm_fallback",
    "radar_capture_poll_seconds", "radar_retention_days",
    "radar_fda_enabled", "radar_fda_product_codes", "radar_fda_keywords",
    "radar_filing_mode", "radar_filing_quiet_minutes", "radar_filing_daily_time",
    "radar_filing_model",
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

    @classmethod
    def settings_customise_sources(cls, settings_cls: type[BaseSettings],
                                   init_settings: PydanticBaseSettingsSource,
                                   env_settings: PydanticBaseSettingsSource,
                                   dotenv_settings: PydanticBaseSettingsSource,
                                   file_secret_settings: PydanticBaseSettingsSource) -> tuple:
        """The usual sources in the usual order; the `.env` file without retired keys."""
        return (init_settings, env_settings, _without_retired(dotenv_settings),
                file_secret_settings)

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
    # Rotating DB backups: the most timestamped snapshots kept in total. Retention keeps the newest
    # two plus the newest of each of the previous five calendar days (at most seven); this is the
    # upper bound on that rule, and a negative value keeps every snapshot. The DB has no other
    # backup, so this is the only safety net.
    backup_keep: int = 7
    # Recency horizon for Daily Brief eligibility, in days, on the publish-day (local_day)
    # axis. Without a horizon the WHOLE never-briefed backlog is eligible; this bounds
    # eligibility to roughly the last 2 weeks while still letting a resumed outage catch up on
    # everything within that window. 0 or a negative value disables the horizon (unbounded
    # backlog eligibility) -- an explicit escape hatch, not the recommended setting.
    brief_horizon_days: int = 14
    # Enables the T2 Jina Reader acquire rung: when a page is bot-walled past T0/T1,
    # escalate to https://r.jina.ai/ which renders JS server-side and returns clean markdown.
    # OFF by default, because it tells an outside service which pages are being read. Privacy note:
    # enabling this sends the FAILING url (not the whole corpus, only pages that reached this
    # rung) to jina.ai for rendering -- turn off if that's unacceptable for a given deployment.
    jina_enabled: bool = False
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

    # ---- Radar (the redesigned product layer) ---------------------------------------------
    # Model for the cheap first pass that judges title and snippet (OpenRouter model id).
    # Chosen by testing against the reader's own saved and rejected items: best recall of the
    # inexpensive models tried.
    radar_triage_model: str = "openai/gpt-6-luna"
    # Model for the second pass that reads the full text and writes headline, why, key points.
    # Chosen for the most concrete, numerically accurate summaries in a side-by-side test.
    radar_digest_model: str = "anthropic/claude-haiku-5.5"
    # Model for small writing jobs: the brief's opening lines, watch discovery, paper ranking.
    radar_writer_model: str = "deepseek/deepseek-v4-flash"
    # Who does the bulk judging and writing: "openrouter" (pay per use, the default) or
    # "claude_code" (the reader's own installed Claude Code, run headless on their plan).
    radar_llm_provider: Literal["openrouter", "claude_code", "gemini", "antigravity"] = "openrouter"
    # Providers to fall back to, in order, when the first one is unavailable (out of credit,
    # usage limit reached, not signed in). Comma-separated names; empty means no fallback.
    radar_llm_fallback: str = ""
    # Models used when the provider is claude_code (aliases or full names the command accepts).
    # Haiku matched Sonnet on the reader's own saved and rejected items (80% vs 81% kept,
    # 95% vs 93% rejected) at a fraction of the usage.
    radar_claude_triage_model: str = "haiku"
    radar_claude_digest_model: str = "haiku"
    radar_claude_writer_model: str = "haiku"
    # Triage score (0-100) an item needs before its full text is fetched and digested.
    radar_digest_gate: int = 50
    # Local time (HH:MM) at which the daily brief is composed.
    radar_brief_time: str = "06:30"
    # IANA time zone the brief day and schedule use; empty means the machine's own zone.
    radar_timezone: str = ""
    # Hours between automatic collections while the service runs.
    radar_collect_hours: float = 2.0
    # Local time (HH:MM) of the daily database backup, in `radar_timezone`; a quiet hour. A PC that
    # was asleep then takes the backup when it next checks and the newest one is over 26 hours old.
    radar_backup_time: str = "03:00"
    # Background filing of the "To file" queue into the vault: "off" (only the visible File now
    # session), "auto" (file first, ask one simple question after) or "plan_first" (propose a
    # plan, file what the reader approves). A run starts when the queue has been quiet for
    # `radar_filing_quiet_minutes`, and once a day at `radar_filing_daily_time` (local HH:MM) as
    # a safety net, on `radar_filing_model`, with the vault skills of the Claude Code plugin
    # `radar_filing_plugin`.
    radar_filing_mode: Literal["off", "auto", "plan_first"] = "off"
    radar_filing_quiet_minutes: int = 10
    radar_filing_daily_time: str = "21:00"
    radar_filing_model: str = "sonnet"
    # The vault skills are configuration, never code: the plugin that holds them and the full
    # names (for example "vault-skills:ingest") of the skill that brings outside material into
    # the vault and of the skill that writes project records. All three are empty by default and
    # set only in the owner's local environment file; with the two skill names or the vault
    # folder unset, filing is "not configured" and the interface hides it.
    radar_filing_plugin: str = ""
    radar_filing_ingest_skill: str = ""
    radar_filing_manage_skill: str = ""
    # FDA device decisions (510(k) clearances, De Novo grants, PMA approvals, recalls) for the
    # watched companies, from the public openFDA service, checked once a day. The two lists add
    # product codes (for example "QAS") and device keywords to look for beyond the watch list.
    radar_fda_enabled: bool = True
    radar_fda_product_codes: str = ""
    radar_fda_keywords: str = ""
    # Run the built-in scheduler (collect, assess, brief, watch sweep). Tests switch it off.
    radar_scheduler: bool = True
    # Skip the older enrichment and brief composer once radar owns the pipeline.
    radar_replaces_legacy: bool = True
    # Gmail newsletters over IMAP: the address, an app password (secret, env only), the label
    # that marks newsletters and the label for links the reader mails to themself.
    gmail_address: str | None = None
    gmail_app_password: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_GMAIL_APP_PASSWORD", "GMAIL_APP_PASSWORD"))
    gmail_newsletter_label: str = "Newsletters"
    gmail_capture_label: str = "Spyglass"
    # Slack capture: a bot token (secret, env only) and the channel id the reader posts into.
    slack_bot_token: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_SLACK_BOT_TOKEN", "SLACK_BOT_TOKEN"))
    slack_capture_channel: str = ""
    # Slack app-level token (secret, env only) for the live connection that delivers a new
    # message within a second or two. Without it the channel is checked on a timer instead.
    slack_app_token: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_SLACK_APP_TOKEN", "SLACK_APP_TOKEN"))
    # Seconds between checks of the capture sources (Slack channel, Gmail label) when no live
    # connection is available.
    radar_capture_poll_seconds: int = 60
    # Days to keep the stored full text and reader document of items the reader never opened,
    # saved or sent in. Titles, summaries and judgements are kept; 0 keeps everything.
    radar_retention_days: int = 120
    # ---- Privacy -------------------------------------------------------------------------
    # Send the titles of items the reader saved or rejected to the judging model as examples
    # of taste. Off means the model sees only the profile's statement, sections and topics.
    privacy_send_examples: bool = True
    # Fetch article images through this service so the reader's browser never contacts the
    # sites that host them (no cookies, no address, no tracking pixels reach those sites).
    privacy_proxy_images: bool = True
    # Let the built-in invisible browser complete a site's automated bot check. Doing so sends
    # that checking service technical details of the browser (never anything personal, never a
    # login). On by default, because many sources (research-lab blogs among them) cannot be read
    # otherwise; with it off, such pages can still be brought in from the reader's own browser.
    privacy_allow_bot_checks: bool = True
    # Assistant engines. Keys are read from the environment or the OS keyring, never stored
    # in the database. The local command-line engines are off until the reader enables them.
    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    gemini_api_key: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"))
    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices(
        "SPYGLASS_OPENAI_API_KEY", "OPENAI_API_KEY"))
    assist_claude_code_enabled: bool = False
    assist_codex_cli_enabled: bool = False
    # Google's Antigravity command line, run headless on the reader's own Google plan.
    assist_antigravity_enabled: bool = False
    radar_antigravity_model: str = ""
    # Default engine id and model for a new assistant thread; empty picks the first available.
    assist_default_engine: str = ""
    assist_default_model: str = ""

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
