"""The bookmark button's secret, the real-sender rules and the cross-site replacement rule.

Backend only: the router is mounted on a small app behind the cross-site guard, like the other
import tests. No test touches the network.
"""

import os
import re
from pathlib import Path

import pytest
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.import_key import KEY_FILE, button_key, key_matches, rotate_button_key
from spyglass_service.radar.import_trust import REPLACE_REFUSED, foreign_sender, host_of, may_replace, same_site
from spyglass_service.radar.importer import ImportRefused, Incoming, import_page
from spyglass_service.radar.models import ReaderDoc

from . import test_import_api as import_api
from .test_import_api import CROSS_SITE, LOCAL, SITE, STAGE, stage_form, stage_json, token_of
from .test_importer import PAGE, URL

# The shared fixtures, registered here under their own names (an assignment, not an import of the
# name, so the tests below may take them as arguments).
env = import_api.env
no_network = import_api.no_network

KEY_URL = "/api/radar/import/button-key"
EVIL = "https://evil.example"
ACCEPT = "/api/radar/import/staged/{}/accept"
PREVIEW = "/api/radar/import/staged/{}"


# ---- the key itself ------------------------------------------------------------------------

def test_the_key_is_128_random_bits_made_once_and_kept(tmp_path: Path) -> None:
    first = button_key(tmp_path)
    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert button_key(tmp_path) == first
    assert (tmp_path / KEY_FILE).read_text(encoding="ascii") == first
    assert button_key(tmp_path / "other") != first


@pytest.mark.skipif(os.name == "nt", reason="file modes are not enforced on Windows")
def test_the_key_file_is_readable_by_the_owner_only(tmp_path: Path) -> None:
    button_key(tmp_path)
    assert (tmp_path / KEY_FILE).stat().st_mode & 0o077 == 0


def test_a_damaged_key_file_is_replaced(tmp_path: Path) -> None:
    (tmp_path / KEY_FILE).write_text("not a key", encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{32}", button_key(tmp_path))


def test_rotating_replaces_the_key_and_the_old_one_stops_working(tmp_path: Path) -> None:
    old = button_key(tmp_path)
    new = rotate_button_key(tmp_path)
    assert new != old and button_key(tmp_path) == new
    assert key_matches(tmp_path, new) and not key_matches(tmp_path, old)


@pytest.mark.parametrize("supplied", [None, "", "abc", 12, "G" * 32, "0" * 31, "0" * 33])
def test_only_the_exact_key_matches(tmp_path: Path, supplied: object) -> None:
    button_key(tmp_path)
    assert key_matches(tmp_path, supplied) is False


# ---- the same-origin key routes ------------------------------------------------------------

def test_the_key_route_gives_the_key_to_this_site_only(env) -> None:
    ok = env.client.get(KEY_URL, headers=LOCAL)
    assert ok.status_code == 200 and ok.json() == {"key": env.key}
    for site in ("cross-site", "same-site"):
        refused = env.client.get(KEY_URL, headers={"Sec-Fetch-Site": site})
        assert refused.status_code == 403 and env.key not in refused.text


def test_rotating_through_the_route_changes_the_key_and_refuses_other_sites(env) -> None:
    assert env.client.post(KEY_URL + "/rotate", headers=CROSS_SITE).status_code == 403
    assert env.client.post(KEY_URL + "/rotate", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert env.client.get(KEY_URL, headers=LOCAL).json()["key"] == env.key
    new = env.client.post(KEY_URL + "/rotate", headers=LOCAL).json()["key"]
    assert new != env.key and env.client.get(KEY_URL, headers=LOCAL).json()["key"] == new
    # A button made with the old key no longer stages anything, on either transport.
    assert stage_json(env).status_code == 403
    assert stage_form(env).headers["location"] == "/#/import?error=key"
    assert stage_json(env, key=new).status_code == 200


# ---- staging needs the key -----------------------------------------------------------------

@pytest.mark.parametrize("key", ["", "0" * 32, "short", None])
def test_the_form_path_refuses_a_missing_or_wrong_key(env, key) -> None:
    fields = {} if key is None else {"key": key}
    data = {"url": URL, "title": "T", "html": PAGE, **fields}
    response = env.client.post(STAGE, files={k: (None, v) for k, v in data.items()}, headers=CROSS_SITE)
    assert response.status_code == 303 and response.headers["location"] == "/#/import?error=key"
    assert not env.staging.exists() or not any(env.staging.iterdir())


@pytest.mark.parametrize("key", ["", "0" * 32, "short"])
def test_the_json_path_refuses_a_wrong_key(env, key: str) -> None:
    response = stage_json(env, key=key)
    assert response.status_code == 403 and "Settings" in response.json()["detail"]


def test_the_json_path_refuses_a_missing_key(env) -> None:
    response = env.client.post(STAGE, json={"url": URL, "html": PAGE}, headers=LOCAL)
    assert response.status_code == 403
    assert not env.staging.exists() or not any(env.staging.iterdir())


def test_a_correct_key_stages_on_both_paths(env) -> None:
    assert stage_json(env).status_code == 200
    assert stage_form(env).status_code == 303


# ---- the form path needs a real sender -----------------------------------------------------

@pytest.mark.parametrize("origin", [None, "null", "", "file://", "chrome-extension://abc"])
def test_the_form_path_refuses_a_missing_or_null_origin(env, origin) -> None:
    headers = {"Sec-Fetch-Site": "cross-site"}
    if origin is not None:
        headers["Origin"] = origin
    response = stage_form(env, headers=headers)
    assert response.status_code == 303 and response.headers["location"] == "/#/import?error=origin"
    assert not env.staging.exists() or not any(env.staging.iterdir())


def test_the_senders_origin_is_kept_with_the_staged_page(env) -> None:
    token = token_of(stage_form(env, headers={"Origin": EVIL + ":8443", "Sec-Fetch-Site": "cross-site"}))
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["sender"] == "evil.example"


# ---- a sender that does not match the address ----------------------------------------------

def add_existing(env, text: str = "Original", url: str = URL) -> int:
    """An item the reader already has at an address (the story's by default)."""
    with Session(env.engine) as session:
        item = Item(source="rss", external_id="e1", title=text, url=url, origin="News Example")
        session.add(item)
        session.commit()
        return item.id


def test_a_matching_sender_changes_nothing(env) -> None:
    item_id = add_existing(env)
    token = stage_json(env, sender="https://news.example.com").json()["token"]
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["sender"] == "news.example.com" and preview["sender_matches"] is True
    assert preview["replaces_existing"] is True and preview["existing_item_id"] == item_id
    assert preview["replace_refused"] is False
    accepted = env.client.post(ACCEPT.format(token), headers=LOCAL)
    assert accepted.status_code == 200 and accepted.json()["id"] == item_id  # replaced, as before
    with Session(env.engine) as session:
        assert session.exec(select(ReaderDoc)).first().status == "ok"


def test_www_and_the_bare_host_are_the_same_host_for_replacing(env) -> None:
    item_id = add_existing(env, url="https://example.org/story")
    token = stage_json(env, url="https://example.org/story", sender="https://www.example.org").json()["token"]
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["replace_refused"] is False
    accepted = env.client.post(ACCEPT.format(token), headers=LOCAL)
    assert accepted.status_code == 200 and accepted.json()["id"] == item_id


def test_two_sub_domains_of_one_shared_suffix_cannot_replace_each_other(env) -> None:
    """The approximate site test calls them one site (the suffix is unknown); replacing needs more."""
    claimed = "https://alice.hosting.io/post"
    add_existing(env, url=claimed)
    token = stage_json(env, url=claimed, sender="https://bob.hosting.io").json()["token"]
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["sender_matches"] is True  # wording only
    assert preview["replaces_existing"] is True and preview["replace_refused"] is True
    refused = env.client.post(ACCEPT.format(token), headers=LOCAL)
    assert refused.status_code == 409 and refused.json()["detail"] == REPLACE_REFUSED


def test_a_sibling_sub_domain_cannot_replace_an_existing_item(env) -> None:
    add_existing(env)
    token = stage_json(env, sender="https://www.example.com").json()["token"]
    assert env.client.post(ACCEPT.format(token), headers=LOCAL).status_code == 409


def test_the_importer_refuses_when_told_the_sender_may_not_replace(env) -> None:
    add_existing(env)
    with pytest.raises(ImportRefused, match="cannot replace"):
        import_page(env.engine, env.app.state.settings, Incoming(url=URL, title="T", html=PAGE, no_replace=True))


def test_the_preview_says_who_sent_a_page_that_claims_another_site(env) -> None:
    token = stage_json(env, sender=EVIL).json()["token"]
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["sender"] == "evil.example" and preview["sender_matches"] is False
    assert preview["replaces_existing"] is False and preview["host"] == "news.example.com"


def test_a_page_from_another_site_cannot_replace_an_existing_item(env) -> None:
    item_id = add_existing(env)
    token = stage_json(env, sender=EVIL).json()["token"]
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["sender_matches"] is False and preview["replaces_existing"] is True
    refused = env.client.post(ACCEPT.format(token), headers=LOCAL)
    assert refused.status_code == 409 and refused.json()["detail"] == REPLACE_REFUSED
    with Session(env.engine) as session:
        assert session.exec(select(ReaderDoc)).all() == []  # nothing was written
        assert session.get(Item, item_id).title == "Original"
    # The page keeps waiting until the reader discards it.
    assert env.client.get(PREVIEW.format(token), headers=LOCAL).status_code == 200
    assert env.client.delete(PREVIEW.format(token), headers=LOCAL).status_code == 204


def test_a_new_item_from_another_site_shows_the_sender_as_its_publication(env) -> None:
    token = stage_json(env, sender=EVIL).json()["token"]
    accepted = env.client.post(ACCEPT.format(token), headers=LOCAL)
    assert accepted.status_code == 200
    item = accepted.json()
    assert item["url"] == URL and item["origin"] == "evil.example"
    with Session(env.engine) as session:
        assert session.exec(select(ReaderDoc)).first().site == "evil.example"


def test_a_page_staged_without_a_known_sender_is_treated_as_foreign(env) -> None:
    add_existing(env)
    token = stage_json(env).json()["token"]
    preview = env.client.get(PREVIEW.format(token), headers=LOCAL).json()
    assert preview["sender"] is None and preview["sender_matches"] is False
    assert env.client.post(ACCEPT.format(token), headers=LOCAL).status_code == 409


def test_the_form_path_records_the_real_origin_so_a_claim_cannot_hide_it(env) -> None:
    add_existing(env)
    token = token_of(stage_form(env, headers={"Origin": EVIL, "Sec-Fetch-Site": "cross-site"}))
    assert env.client.post(ACCEPT.format(token), headers=LOCAL).status_code == 409
    assert SITE not in env.client.get(PREVIEW.format(token), headers=LOCAL).text.replace(URL, "")


def test_the_importer_itself_refuses_a_foreign_replacement(env) -> None:
    add_existing(env)
    with pytest.raises(ImportRefused, match="cannot replace"):
        import_page(env.engine, env.app.state.settings,
                    Incoming(url=URL, title="T", html=PAGE, foreign_sender="evil.example", no_replace=True))


# ---- the comparison ------------------------------------------------------------------------

@pytest.mark.parametrize("sender,claimed,expected", [
    ("www.example.com", "news.example.com", True),
    ("example.com", "example.com", True),
    ("news.bbc.co.uk", "www.bbc.co.uk", True),
    ("example.org", "example.com", False),
    ("evil.co.uk", "bbc.co.uk", False),
    ("alice.github.io", "bob.github.io", False),
    ("10.0.0.1", "10.0.0.1", True),
    ("10.0.0.1", "10.0.0.2", False),
    (None, "example.com", False),
    ("example.com", None, False),
])
def test_same_site(sender, claimed, expected: bool) -> None:
    assert same_site(sender, claimed) is expected


@pytest.mark.parametrize("sender,address,expected", [
    ("https://news.example.com", "https://news.example.com/a", True),
    ("https://NEWS.example.com:8443", "https://news.example.com/a", True),
    ("https://www.example.org", "https://example.org/a", True),
    ("https://example.org", "https://www.example.org/a", True),
    ("https://www.example.com", "https://news.example.com/a", False),
    ("https://alice.hosting.io", "https://bob.hosting.io/a", False),
    ("https://alice.github.io", "https://bob.github.io/a", False),
    ("https://evil.example", "https://news.example.com/a", False),
    ("https://www.www.example.org", "https://example.org/a", False),
    ("http://10.0.0.1", "https://10.0.0.2/a", False),
    (None, "https://news.example.com/a", False),
    ("null", "https://news.example.com/a", False),
])
def test_may_replace_compares_exact_hosts_ignoring_only_case_and_www(sender, address, expected: bool) -> None:
    assert may_replace(sender, address) is expected


def test_foreign_sender_and_host_of() -> None:
    assert foreign_sender("https://www.example.com", "https://news.example.com/a") is None
    assert foreign_sender("https://evil.example:8443", "https://news.example.com/a") == "evil.example"
    assert foreign_sender(None, "https://news.example.com/a") == "unknown site"
    assert host_of("https://News.Example.com.:8443/x") == "news.example.com"
    assert host_of("null") is None and host_of(None) is None
