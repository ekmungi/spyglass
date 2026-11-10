"""Smoke test proving the test harness and package wiring work."""

import spyglass_service


def test_package_exposes_version() -> None:
    """The package declares a semantic version string."""
    major, minor, patch = spyglass_service.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))
