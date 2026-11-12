"""A `.env` file that still names a removed setting must not stop the service from starting."""

import logging

from spyglass_service.config import Settings


def test_a_removed_key_in_the_env_file_is_ignored_with_one_log_line(tmp_path, caplog):
    env_file = tmp_path / ".env"
    env_file.write_text("SPYGLASS_RADAR_VAULT_SUBDIR=Old/Folder\nSPYGLASS_PORT=7790\n",
                        encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="spyglass_service.config"):
        settings = Settings(_env_file=env_file)
    assert settings.port == 7790
    assert not hasattr(settings, "radar_vault_subdir")
    lines = [r for r in caplog.records if "SPYGLASS_RADAR_VAULT_SUBDIR" in r.getMessage()]
    assert len(lines) == 1


def test_an_unknown_key_that_was_never_a_setting_still_fails(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SPYGLASS_NOT_A_SETTING=1\n", encoding="utf-8")
    try:
        Settings(_env_file=env_file)
    except ValueError as exc:
        assert "not_a_setting" in str(exc).lower()
    else:
        raise AssertionError("an unknown key should still be refused")


def test_the_filing_settings_default_to_off():
    settings = Settings(_env_file=None)
    assert settings.radar_filing_mode == "off"
    assert settings.radar_filing_quiet_minutes == 10
    assert settings.radar_filing_daily_time == "21:00"
