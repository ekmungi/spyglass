"""Fixtures shared by the radar tests."""

import pytest


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer every host-name lookup with a fixed public address, so no test touches DNS.

    Tests that need a name to resolve to a private address patch `netguard.resolve` themselves.
    """
    monkeypatch.setattr(
        "spyglass_service.radar.netguard.resolve", lambda host: ["93.184.216.34"]
    )


@pytest.fixture(autouse=True)
def _fresh_provider_memory():
    """Forget which AI providers were unavailable, so one test never affects the next."""
    from spyglass_service.radar import llm_chain

    llm_chain.COOLDOWNS.reset()
    yield
    llm_chain.COOLDOWNS.reset()
