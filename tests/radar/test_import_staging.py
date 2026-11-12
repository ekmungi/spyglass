"""Tests for the import staging area: where a page handed over from the browser waits for the
reader to confirm it. Nothing here touches the network or the database."""

import os
import re
from pathlib import Path

import pytest

from spyglass_service.radar import import_staging
from spyglass_service.radar.import_staging import StagingArea, StagingError

URL = "https://news.example.com/story"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def make_area(tmp_path: Path, clock: Clock | None = None) -> StagingArea:
    return StagingArea(tmp_path / "import_staging", clock=clock or Clock())


def test_a_staged_page_can_be_previewed_and_then_taken_once(tmp_path: Path) -> None:
    area = make_area(tmp_path)
    token = area.stage(URL, "A title", "<html><body><p>Hello</p></body></html>", sender="https://news.example.com")
    page = area.peek(token)
    assert (page.url, page.title, page.sender) == (URL, "A title", "https://news.example.com")
    assert "Hello" in page.html
    assert area.peek(token).html == page.html  # peeking does not consume
    taken = area.take(token)
    assert taken.html == page.html
    with pytest.raises(LookupError):
        area.take(token)
    with pytest.raises(LookupError):
        area.peek(token)
    assert list((tmp_path / "import_staging").iterdir()) == []


def test_the_token_is_128_bits_of_hex_and_names_the_file(tmp_path: Path) -> None:
    area = make_area(tmp_path)
    tokens = {area.stage(URL, "", "<p>x</p>") for _ in range(5)}
    assert len(tokens) == 5
    assert all(re.fullmatch(r"[0-9a-f]{32}", token) for token in tokens)
    names = {path.stem for path in (tmp_path / "import_staging").iterdir()}
    assert names == tokens


def test_the_token_comes_from_the_secrets_module(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    def fake_token_hex(nbytes: int) -> str:
        calls.append(nbytes)
        return "ab" * nbytes

    monkeypatch.setattr(import_staging.secrets, "token_hex", fake_token_hex)
    token = make_area(tmp_path).stage(URL, "", "<p>x</p>")
    assert calls == [16] and token == "ab" * 16


@pytest.mark.parametrize("token", ["", "../../etc/passwd", "ABCDEF" * 6, "0" * 31, "0" * 33,
                                   "g" * 32, "0" * 30 + "/x"])
def test_a_malformed_token_is_unknown_and_never_touches_the_disk(tmp_path: Path, token: str) -> None:
    area = make_area(tmp_path)
    with pytest.raises(LookupError):
        area.peek(token)
    with pytest.raises(LookupError):
        area.take(token)
    assert area.discard(token) is False


def test_discard_removes_the_page(tmp_path: Path) -> None:
    area = make_area(tmp_path)
    token = area.stage(URL, "", "<p>x</p>")
    assert area.discard(token) is True
    assert area.discard(token) is False
    with pytest.raises(LookupError):
        area.peek(token)


def test_a_page_expires_after_fifteen_minutes(tmp_path: Path) -> None:
    clock = Clock()
    area = make_area(tmp_path, clock)
    token = area.stage(URL, "", "<p>x</p>")
    clock.now += 14 * 60
    assert area.peek(token).url == URL
    clock.now += 2 * 60
    with pytest.raises(LookupError):
        area.peek(token)
    with pytest.raises(LookupError):
        area.take(token)
    area.purge()
    assert list((tmp_path / "import_staging").iterdir()) == []


def test_staging_purges_expired_pages(tmp_path: Path) -> None:
    clock = Clock()
    area = make_area(tmp_path, clock)
    old = area.stage(URL, "", "<p>old</p>")
    clock.now += 16 * 60
    area.stage(URL, "", "<p>new</p>")
    names = {path.stem for path in (tmp_path / "import_staging").iterdir()}
    assert old not in names and len(names) == 1


def test_never_more_than_twenty_pages_wait_and_the_oldest_goes_first(tmp_path: Path) -> None:
    clock = Clock()
    area = make_area(tmp_path, clock)
    tokens = []
    for _ in range(35):
        clock.now += 1
        tokens.append(area.stage(URL, "", "<p>x</p>"))
    files = list((tmp_path / "import_staging").iterdir())
    assert len(files) == import_staging.MAX_ENTRIES == 20
    assert {path.stem for path in files} == set(tokens[-20:])
    assert area.peek(tokens[-1]).url == URL


def test_the_total_size_stays_under_sixty_megabytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(import_staging, "MAX_TOTAL_BYTES", 10_000)
    clock = Clock()
    area = make_area(tmp_path, clock)
    for _ in range(30):
        clock.now += 1
        area.stage(URL, "", "<p>" + "x" * 3_000 + "</p>")
        total = sum(path.stat().st_size for path in (tmp_path / "import_staging").iterdir())
        assert total <= 10_000
    assert import_staging.MAX_TOTAL_BYTES == 10_000
    monkeypatch.undo()
    assert import_staging.MAX_TOTAL_BYTES == 60 * 1024 * 1024


def test_a_page_over_the_size_cap_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(import_staging, "MAX_HTML_BYTES", 100)
    area = make_area(tmp_path)
    with pytest.raises(StagingError):
        area.stage(URL, "", "<p>" + "x" * 200 + "</p>")
    assert not (tmp_path / "import_staging").exists() or not any((tmp_path / "import_staging").iterdir())


def test_the_html_cap_is_counted_in_utf8_bytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(import_staging, "MAX_HTML_BYTES", 100)
    area = make_area(tmp_path)
    with pytest.raises(StagingError):
        area.stage(URL, "", "é" * 60)  # 60 characters, 120 bytes


def test_empty_html_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StagingError):
        make_area(tmp_path).stage(URL, "", "   ")


def test_a_long_title_is_cut_and_control_characters_removed(tmp_path: Path) -> None:
    area = make_area(tmp_path)
    token = area.stage(URL, "A\x00B\nC" + "t" * 2_000, "<p>x</p>", sender="x" * 500)
    page = area.peek(token)
    assert page.title.startswith("A B C")
    assert len(page.title) <= import_staging.MAX_TITLE_CHARS
    assert page.sender is None or len(page.sender) <= 200


def test_leftover_temporary_files_are_cleared_when_old(tmp_path: Path) -> None:
    clock = Clock()
    area = make_area(tmp_path, clock)
    folder = tmp_path / "import_staging"
    folder.mkdir(parents=True)
    stray = folder / "0123.tmp"
    stray.write_text("half written")
    os.utime(stray, (clock.now, clock.now))
    clock.now += 16 * 60
    area.purge()
    assert not stray.exists()


def test_a_damaged_file_is_treated_as_missing(tmp_path: Path) -> None:
    area = make_area(tmp_path)
    token = area.stage(URL, "", "<p>x</p>")
    (tmp_path / "import_staging" / f"{token}.json").write_text("not json")
    with pytest.raises(LookupError):
        area.peek(token)


def test_the_background_sweep_deletes_a_page_nobody_answered(tmp_path: Path) -> None:
    clock = Clock()
    area = make_area(tmp_path, clock)
    area.stage(URL, "", "<p>never answered</p>")
    import_staging.sweep_once()
    assert len(list((tmp_path / "import_staging").glob("*.json"))) == 1
    clock.now += 16 * 60
    import_staging.sweep_once()
    assert list((tmp_path / "import_staging").iterdir()) == []


def test_staging_starts_one_background_sweeper(tmp_path: Path) -> None:
    make_area(tmp_path).stage(URL, "", "<p>x</p>")
    sweeper = import_staging._sweeper
    assert sweeper is not None and sweeper.daemon and sweeper.is_alive()
    make_area(tmp_path / "other").stage(URL, "", "<p>y</p>")
    assert import_staging._sweeper is sweeper
