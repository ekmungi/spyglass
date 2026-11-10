"""Tests for the service configuration module."""

from pathlib import Path

from spyglass_service.config import Settings, OVERLAY_KEYS, apply_overlay, save_overlay


def test_defaults_bind_localhost_on_port_7777() -> None:
    """Without overrides the service binds 127.0.0.1:7777 (localhost-only by design)."""
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.port == 7777


def test_default_data_dir_is_dot_spyglass_in_home(monkeypatch) -> None:
    """Operational state defaults to ~/.spyglass, never a cloud-synced vault folder."""
    monkeypatch.delenv("SPYGLASS_DATA_DIR", raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path.home() / ".spyglass"
    assert "OneDrive" not in str(settings.data_dir)


def test_db_path_is_inside_data_dir() -> None:
    """The SQLite app database is a file inside the data dir."""
    settings = Settings(_env_file=None)
    assert settings.db_path.parent == settings.data_dir
    assert settings.db_path.suffix == ".db"


def test_vault_path_is_unset_by_default() -> None:
    """The vault location must be configured explicitly; no guessing."""
    settings = Settings(_env_file=None)
    assert settings.vault_path is None


def test_effective_preferences_path_defaults_under_data_dir(tmp_path) -> None:
    """With no explicit value the learning note resolves to a fixed file by the DB."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert settings.effective_preferences_note_path == (tmp_path / "data" / "preferences.md")


def test_effective_preferences_path_uses_explicit_value(tmp_path) -> None:
    """A configured preferences note path overrides the fixed default."""
    explicit = tmp_path / "vault" / "prefs.md"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", preferences_note_path=explicit)
    assert settings.effective_preferences_note_path == explicit


def test_env_variables_override_defaults(monkeypatch) -> None:
    """SPYGLASS_-prefixed environment variables override every default."""
    monkeypatch.setenv("SPYGLASS_PORT", "9100")
    monkeypatch.setenv("SPYGLASS_VAULT_PATH", "C:/tmp/vault")
    settings = Settings(_env_file=None)
    assert settings.port == 9100
    assert settings.vault_path == Path("C:/tmp/vault")


def test_data_dir_overridable_via_env(monkeypatch, tmp_path) -> None:
    """SPYGLASS_DATA_DIR relocates the operational home -- the plugin sets this."""
    monkeypatch.setenv("SPYGLASS_DATA_DIR", str(tmp_path / "spy"))
    settings = Settings(_env_file=None)
    assert settings.data_dir == tmp_path / "spy"
    assert settings.db_path == tmp_path / "spy" / "spyglass.db"


def test_models_dir_is_inside_data_dir(tmp_path) -> None:
    """The FastEmbed model cache lives under the data dir."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.models_dir == tmp_path / "models"


def test_enrich_defaults(monkeypatch) -> None:
    """Enrichment fields have the right defaults when no env vars are set."""
    monkeypatch.delenv("SPYGLASS_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # _env_file=None so a developer's local .env (which may hold a real OPENROUTER_API_KEY,
    # read via AliasChoices) cannot make this defaults assertion flake.
    s = Settings(_env_file=None)
    assert s.enrich_model == "deepseek/deepseek-v4-flash"
    assert s.relevance_gate == 40
    assert s.embedder == "arctic"
    assert s.openrouter_api_key is None


def test_openrouter_key_from_plain_env(monkeypatch) -> None:
    """Unprefixed OPENROUTER_API_KEY is accepted via AliasChoices."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    assert Settings().openrouter_api_key == "sk-test"


def test_api_key_not_overlay_editable() -> None:
    """openrouter_api_key must not be in OVERLAY_KEYS; enrich_model and relevance_gate must be."""
    assert "openrouter_api_key" not in OVERLAY_KEYS
    assert "enrich_model" in OVERLAY_KEYS
    assert "relevance_gate" in OVERLAY_KEYS


def test_brief_horizon_days_defaults_to_fourteen() -> None:
    """Default recency horizon is ~2 weeks."""
    settings = Settings(_env_file=None)
    assert settings.brief_horizon_days == 14


def test_brief_horizon_days_env_override(monkeypatch) -> None:
    """SPYGLASS_BRIEF_HORIZON_DAYS overrides the default like every other env-tunable setting."""
    monkeypatch.setenv("SPYGLASS_BRIEF_HORIZON_DAYS", "30")
    settings = Settings(_env_file=None)
    assert settings.brief_horizon_days == 30


def test_brief_horizon_days_is_overlay_editable() -> None:
    """brief_horizon_days is dashboard-tunable without a restart (settings.json overlay)."""
    assert "brief_horizon_days" in OVERLAY_KEYS


def test_brief_horizon_days_overlay_round_trip(tmp_path: Path) -> None:
    """A saved overlay value for brief_horizon_days is re-applied on the next load,
    the same persistence path every other OVERLAY_KEYS setting uses."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    save_overlay(settings, {"brief_horizon_days": 30})
    reloaded = apply_overlay(settings)
    assert reloaded.brief_horizon_days == 30


def test_jina_enabled_defaults_to_true() -> None:
    """The T2 Jina Reader rung is ON by default -- no opt-in required to get the
    bot-wall-clearing benefit."""
    settings = Settings(_env_file=None)
    assert settings.jina_enabled is True


def test_jina_api_key_defaults_to_none() -> None:
    """No API key is required -- keyless Jina works at a lower (~20 req/min) rate limit."""
    monkeypatch_env_cleared = Settings(_env_file=None)
    assert monkeypatch_env_cleared.jina_api_key is None


def test_jina_api_key_from_plain_env(monkeypatch) -> None:
    """Unprefixed JINA_API_KEY is accepted via AliasChoices, mirroring openrouter_api_key."""
    monkeypatch.setenv("JINA_API_KEY", "jina-test-key")
    assert Settings(_env_file=None).jina_api_key == "jina-test-key"


def test_jina_api_key_from_prefixed_env(monkeypatch) -> None:
    """SPYGLASS_JINA_API_KEY (the project's usual env prefix) also works."""
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.setenv("SPYGLASS_JINA_API_KEY", "sk-jina-prefixed")
    assert Settings(_env_file=None).jina_api_key == "sk-jina-prefixed"


def test_jina_enabled_is_overlay_editable() -> None:
    """jina_enabled is dashboard-tunable (future UI)."""
    assert "jina_enabled" in OVERLAY_KEYS


def test_jina_api_key_not_overlay_editable() -> None:
    """jina_api_key is a secret, like openrouter_api_key -- never dashboard-editable."""
    assert "jina_api_key" not in OVERLAY_KEYS


def test_jina_enabled_env_override(monkeypatch) -> None:
    """SPYGLASS_JINA_ENABLED overrides the default like every other env-tunable setting."""
    monkeypatch.setenv("SPYGLASS_JINA_ENABLED", "false")
    settings = Settings(_env_file=None)
    assert settings.jina_enabled is False


def test_browser_enabled_defaults_to_true() -> None:
    """The T3 patchright browser rung is ON by default -- last-resort local rendering is
    available out of the box."""
    settings = Settings(_env_file=None)
    assert settings.browser_enabled is True


def test_browser_enabled_env_override(monkeypatch) -> None:
    """SPYGLASS_BROWSER_ENABLED overrides the default like every other env-tunable setting."""
    monkeypatch.setenv("SPYGLASS_BROWSER_ENABLED", "false")
    settings = Settings(_env_file=None)
    assert settings.browser_enabled is False


def test_browser_enabled_is_overlay_editable() -> None:
    """browser_enabled is dashboard-tunable (future UI), like jina_enabled."""
    assert "browser_enabled" in OVERLAY_KEYS


def test_browser_enabled_overlay_round_trip(tmp_path: Path) -> None:
    """A saved overlay value for browser_enabled is re-applied on the next load."""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    save_overlay(settings, {"browser_enabled": False})
    reloaded = apply_overlay(settings)
    assert reloaded.browser_enabled is False
