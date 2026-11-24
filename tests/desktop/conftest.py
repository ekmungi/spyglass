"""Guards for every desktop test: nothing may reach the real settings folder or the real screen.

The desktop entry's crash guard writes launcher-crash.log beside desktop.json and shows a message
box. A test whose stand-in fails unexpectedly (a wrong signature, say) would otherwise write the
real %LOCALAPPDATA%\\Spyglass\\launcher-crash.log and open a real "Spyglass could not start" box on
the screen. Each test therefore starts with a scratch desktop.json and no operating-system
platform for the crash path; a test that sets its own values afterwards still wins.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _keep_desktop_tests_off_the_real_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point desktop.json at a scratch folder and send crash messages to stderr, not a box."""
    from spyglass_service.desktop import __main__ as desktop_main

    monkeypatch.setenv("SPYGLASS_DESKTOP_CONFIG", str(tmp_path / "guarded-settings" / "desktop.json"))
    monkeypatch.setattr(desktop_main, "default_platform", lambda: None)
    # The setup helper's tests also honour this: messages go to stderr instead of a box.
    monkeypatch.setenv("SPYGLASS_LAUNCHER_NO_DIALOG", "1")
