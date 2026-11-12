"""Tests for the outbound-request guard."""

import pytest

from spyglass_service.radar import netguard

PUBLIC = ["93.184.216.34"]


@pytest.mark.parametrize("url", [
    "https://example.org/a", "http://example.org:8080/x?y=1", "https://8.8.8.8/",
])
def test_public_addresses_are_allowed(url: str) -> None:
    assert netguard.is_public_url(url, resolver=lambda host: PUBLIC)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "ftp://example.org/x", "", "https://",
    "http://localhost/", "http://app.localhost/", "http://printer.local/", "http://127.0.0.1/",
    "http://10.0.0.5/", "http://192.168.1.1/admin", "http://169.254.169.254/latest",
    "http://[::1]/", "http://0.0.0.0/", "https://user:secret@example.org/",
])
def test_non_public_addresses_are_refused(url: str) -> None:
    assert not netguard.is_public_url(url, resolver=lambda host: PUBLIC)


def test_name_resolving_to_a_private_address_is_refused() -> None:
    assert not netguard.is_public_url("https://sneaky.example.org/", resolver=lambda h: ["10.1.2.3"])


def test_name_with_one_private_answer_among_public_ones_is_refused() -> None:
    answers = ["93.184.216.34", "127.0.0.1"]
    assert not netguard.is_public_url("https://mixed.example.org/", resolver=lambda h: answers)


def test_unresolvable_name_is_refused() -> None:
    def fail(_host: str) -> list[str]:
        raise OSError("no such host")

    assert not netguard.is_public_url("https://nowhere.example.org/", resolver=fail)


def test_private_address_literals_are_recognised() -> None:
    assert netguard.is_private_address("192.168.0.10")
    assert netguard.is_private_address("[::1]")
    assert netguard.is_private_address("100.64.1.1")
    assert netguard.is_private_address("64:ff9b::a00:1")
    assert not netguard.is_private_address("93.184.216.34")
    assert not netguard.is_private_address("example.org")
