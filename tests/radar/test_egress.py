"""A secret goes only to its own service: the binding table and the check that enforces it."""

import httpx
import pytest

from spyglass_service.radar import egress
from spyglass_service.radar.egress import (
    SECRET_HOSTS,
    SecretDestinationError,
    UnsafeQuery,
    api_client,
    assert_secret_destination,
    engine_secret_name,
    safe_search_query,
)

WRONG = ("https://evil.example/collect", "https://openrouter.ai.evil.example/x",
         "https://evil.example/?next=https://openrouter.ai/", "ftp://openrouter.ai/x")


@pytest.mark.parametrize("name", sorted(SECRET_HOSTS))
def test_every_secret_passes_for_its_own_host(name: str) -> None:
    """Each secret may travel to every host bound to it, over an encrypted connection."""
    for host in SECRET_HOSTS[name]:
        scheme = "imaps" if host.startswith("imap.") else "https"
        assert_secret_destination(name, f"{scheme}://{host}/path?q=1")


@pytest.mark.parametrize("name", sorted(SECRET_HOSTS))
@pytest.mark.parametrize("url", WRONG)
def test_every_secret_is_refused_anywhere_else(name: str, url: str) -> None:
    """Any other host, a look-alike host or another scheme raises before a request is made."""
    with pytest.raises(SecretDestinationError):
        assert_secret_destination(name, url)


@pytest.mark.parametrize("name", sorted(SECRET_HOSTS))
def test_a_secret_never_travels_in_clear_text_or_with_user_info(name: str) -> None:
    """Plain http to the right host, or an address with user info, is refused."""
    host = sorted(SECRET_HOSTS[name])[0]
    with pytest.raises(SecretDestinationError):
        assert_secret_destination(name, f"http://{host}/")
    with pytest.raises(SecretDestinationError):
        assert_secret_destination(name, f"https://user:pw@{host}/")


def test_a_fixed_secret_cannot_be_widened_by_a_bound_host() -> None:
    """Passing a bound host never lets a settings secret go to that host."""
    with pytest.raises(SecretDestinationError):
        assert_secret_destination("openrouter_api_key", "https://evil.example/",
                                  bound_host="evil.example")


def test_an_unknown_secret_name_is_refused() -> None:
    """A name missing from the table fails closed."""
    with pytest.raises(SecretDestinationError):
        assert_secret_destination("mystery_token", "https://openrouter.ai/")


def test_an_engine_key_goes_only_to_that_engines_own_host() -> None:
    """A key stored for one assistant server is bound to that server's configured host."""
    name = engine_secret_name("custom-lab")
    assert_secret_destination(name, "https://models.lab.example/v1/chat", bound_host="models.lab.example")
    assert_secret_destination(name, "http://127.0.0.1:8080/v1", bound_host="127.0.0.1")
    with pytest.raises(SecretDestinationError):
        assert_secret_destination(name, "https://evil.example/v1", bound_host="models.lab.example")
    with pytest.raises(SecretDestinationError):
        assert_secret_destination(name, "http://models.lab.example/v1", bound_host="models.lab.example")
    with pytest.raises(SecretDestinationError):
        assert_secret_destination(name, "https://models.lab.example/v1")


def test_engine_secret_names_map_preset_engines_to_their_settings_secret() -> None:
    """The preset engines share the settings secret's binding; others get their own name."""
    assert engine_secret_name("openrouter") == "openrouter_api_key"
    assert engine_secret_name("anthropic") == "anthropic_api_key"
    assert engine_secret_name("openai") == "openai_api_key"
    assert engine_secret_name("ollama") == "engine:ollama"


def test_api_client_refuses_a_request_to_another_host_before_sending() -> None:
    """The model-API client checks every request; a refused one never reaches the transport."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={})

    with api_client("openrouter_api_key", transport=httpx.MockTransport(handler)) as client:
        assert client.get("https://openrouter.ai/api/v1/models").status_code == 200
        with pytest.raises(SecretDestinationError):
            client.get("https://evil.example/api/v1/models")
    assert sent == ["https://openrouter.ai/api/v1/models"]


def test_api_client_does_not_follow_redirects() -> None:
    """A redirect answer is returned as it is, never followed with the key attached."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    with api_client("anthropic_api_key", transport=httpx.MockTransport(handler)) as client:
        assert client.get("https://api.anthropic.com/v1/messages").status_code == 302


@pytest.mark.parametrize("query", ['"Olympus" endoscopy AI', "FDA clearance OR approval",
                                   "drug discovery AI"])
def test_safe_search_query_accepts_plain_search_text(query: str) -> None:
    """Ordinary search strings, with quotes and OR, pass unchanged."""
    assert safe_search_query(query) == query


@pytest.mark.parametrize("query", ["", "   ", "x" * 201, "see https://evil.example/a",
                                   "www.evil.example/collect", "a\x00b", "line\nbreak",
                                   "evil.example/path?x=1", 42])
def test_safe_search_query_refuses_urls_control_text_and_long_strings(query: object) -> None:
    """Empty, over-long, non-text, multi-line or address-carrying queries raise."""
    with pytest.raises(UnsafeQuery):
        safe_search_query(query)  # type: ignore[arg-type]


def test_destinations_table_lists_every_secret_bound_host() -> None:
    """Every host a secret may go to is also a documented destination."""
    documented = egress.documented_hosts()
    for hosts in SECRET_HOSTS.values():
        assert hosts <= documented


def test_api_client_without_a_secret_refuses_any_credential_header() -> None:
    """A keyless client (a local server) never carries a credential header anywhere."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={})

    with api_client(None, transport=httpx.MockTransport(handler)) as client:
        assert client.get("http://127.0.0.1:11434/v1/models").status_code == 200
        with pytest.raises(SecretDestinationError):
            client.get("http://127.0.0.1:11434/v1/models", headers={"Authorization": "Bearer x"})
    assert sent == ["http://127.0.0.1:11434/v1/models"]
