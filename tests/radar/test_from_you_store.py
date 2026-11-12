"""The durable store for files the reader sent in: pictures and PDFs that cache trimming never touches."""

import pytest
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar import from_you_store as store
from spyglass_service.radar import housekeeping, media_proxy
from spyglass_service.radar.import_image import image_fields
from spyglass_service.radar.models import ItemState, ReaderDoc

from .test_sources_support import make_engine

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 30
PDF = b"%PDF-1.4 " + b"x" * 40
URL = "https://team.slack.com/files/U1/F200/chart.png"


@pytest.fixture()
def engine(tmp_path):
    engine = make_engine(tmp_path)
    yield engine
    engine.dispose()


def add_picture_item(engine, url: str = URL, *, from_user: bool = True) -> int:
    """An item whose document is the picture at `url` (as an imported picture's is)."""
    with Session(engine) as session:
        item = Item(source="capture", external_id=url, title="chart", url=url)
        session.add(item)
        session.commit()
        fields = image_fields(url, "chart", None)
        session.add(ReaderDoc(item_id=item.id, kind="article", html=fields["html"],
                              lead_image=url, source_url=url))
        session.add(ItemState(item_id=item.id, from_user=from_user, captured_via="slack"))
        session.commit()
        return item.id


# ---- the store ---------------------------------------------------------------------------------


@pytest.mark.parametrize("data,media,suffix", [
    (PNG, "image/png", ".png"), (JPEG, "image/jpeg", ".jpg"), (WEBP, "image/webp", ".webp"),
    (PDF, "application/pdf", ".pdf")])
def test_a_file_is_stored_under_the_item_with_its_type_read_from_its_bytes(tmp_path, data, media, suffix) -> None:
    assert store.put(tmp_path, 7, data) == media
    path, kind = store.find(tmp_path, 7)
    assert kind == media and path.suffix == suffix and path.read_bytes() == data
    assert path.parent == tmp_path / "media" / "from_you" and path.name == f"7{suffix}"


@pytest.mark.parametrize("data", [b"<svg xmlns=\"http://www.w3.org/2000/svg\"/>", b"<html></html>", b"", b"GIF89a"])
def test_bytes_that_are_not_a_picture_or_a_pdf_are_refused(tmp_path, data) -> None:
    with pytest.raises(ValueError):
        store.put(tmp_path, 7, data)
    assert store.find(tmp_path, 7) is None


def test_the_type_comes_from_the_bytes_not_from_the_name(tmp_path) -> None:
    """A PDF renamed .png is still a PDF."""
    store.put(tmp_path, 3, PDF)
    folder = tmp_path / "media" / "from_you"
    (folder / "3.pdf").rename(folder / "3.png")
    assert store.find(tmp_path, 3)[1] == "application/pdf"


def test_a_second_file_for_the_same_item_replaces_the_first(tmp_path) -> None:
    store.put(tmp_path, 4, PNG)
    store.put(tmp_path, 4, PDF)
    assert sorted(p.name for p in (tmp_path / "media" / "from_you").iterdir()) == ["4.pdf"]


def test_remove_deletes_the_file_and_is_fine_when_there_is_none(tmp_path) -> None:
    store.put(tmp_path, 5, PNG)
    assert store.remove(tmp_path, 5) == 1
    assert store.find(tmp_path, 5) is None
    assert store.remove(tmp_path, 5) == 0
    assert store.remove(tmp_path / "nowhere", 5) == 0


def test_size_counts_every_stored_file(tmp_path) -> None:
    assert store.size_bytes(tmp_path) == 0
    store.put(tmp_path, 1, PNG)
    store.put(tmp_path, 2, PDF)
    assert store.size_bytes(tmp_path) == len(PNG) + len(PDF)


# ---- serving through the image route -----------------------------------------------------------


def test_a_stored_picture_is_served_with_no_network_and_no_cache(tmp_path, engine, monkeypatch) -> None:
    item_id = add_picture_item(engine)
    store.put(tmp_path, item_id, PNG)
    monkeypatch.setattr(media_proxy, "_client_factory", lambda: pytest.fail("no fetch"))
    assert media_proxy.serve(engine, tmp_path, URL) == (PNG, "image/png")


def test_cache_trimming_never_removes_a_stored_picture(tmp_path, engine, monkeypatch) -> None:
    item_id = add_picture_item(engine)
    store.put(tmp_path, item_id, PNG)
    cache = tmp_path / "img_cache"
    media_proxy.cache_put(cache, "https://cdn.example.org/a.png", PNG, "image/png")
    monkeypatch.setattr(housekeeping, "IMG_CACHE_BYTES", 0)
    housekeeping._prune_caches(type("S", (), {"data_dir": tmp_path})())
    assert not any(cache.glob("*.img"))
    assert media_proxy.serve(engine, tmp_path, URL) == (PNG, "image/png")


def test_a_stored_file_is_only_served_for_the_address_of_its_own_item(tmp_path, engine) -> None:
    item_id = add_picture_item(engine)
    store.put(tmp_path, item_id, PNG)
    other = "https://team.slack.com/files/U1/F999/other.png"
    assert store.image_for_address(engine, tmp_path, other) is None
    for hostile in ("../media/from_you/1.png", "file:///x.png", "1", "/media/from_you/1.png"):
        assert store.image_for_address(engine, tmp_path, hostile) is None


def test_a_stored_file_that_is_a_pdf_is_not_served_as_a_picture(tmp_path, engine) -> None:
    item_id = add_picture_item(engine)
    store.put(tmp_path, item_id, PDF)
    assert store.image_for_address(engine, tmp_path, URL) is None


def test_a_stored_picture_over_the_size_cap_is_not_served(tmp_path, engine, monkeypatch) -> None:
    item_id = add_picture_item(engine)
    store.put(tmp_path, item_id, PNG)
    monkeypatch.setattr(store, "MAX_PICTURE_BYTES", len(PNG) - 1)
    assert store.image_for_address(engine, tmp_path, URL) is None


# ---- moving what is still in the caches --------------------------------------------------------


def test_pictures_and_pdfs_you_sent_are_moved_out_of_the_caches_once(tmp_path, engine) -> None:
    picture = add_picture_item(engine)
    media_proxy.cache_put(tmp_path / "img_cache", URL, PNG, "image/png")
    with Session(engine) as session:
        item = Item(source="capture", external_id="p", title="paper",
                    url="https://team.slack.com/files/U1/F1/p.pdf")
        session.add(item)
        session.commit()
        pdf = item.id
        session.add(ReaderDoc(item_id=pdf, kind="pdf", html="<p>This is the PDF you added, shown below.</p>"))
        session.add(ItemState(item_id=pdf, from_user=True, captured_via="slack"))
        session.commit()
    (tmp_path / "pdf_cache").mkdir()
    (tmp_path / "pdf_cache" / f"{pdf}.pdf").write_bytes(PDF)

    assert store.move_from_caches(engine, tmp_path) == {"images": 1, "pdfs": 1}

    assert store.find(tmp_path, picture)[0].read_bytes() == PNG
    assert store.find(tmp_path, pdf)[0].read_bytes() == PDF
    assert media_proxy.cache_get(tmp_path / "img_cache", URL) is None
    assert not (tmp_path / "pdf_cache" / f"{pdf}.pdf").exists()
    assert store.move_from_caches(engine, tmp_path) == {"images": 0, "pdfs": 0}


def test_pictures_and_pdfs_you_did_not_send_stay_in_the_caches(tmp_path, engine) -> None:
    add_picture_item(engine, from_user=False)
    media_proxy.cache_put(tmp_path / "img_cache", URL, PNG, "image/png")
    with Session(engine) as session:
        item = Item(source="rss", external_id="a", title="paper", url="https://arxiv.org/abs/2401.00001")
        session.add(item)
        session.commit()
        session.add(ReaderDoc(item_id=item.id, kind="pdf", html="<p>Abstract</p>",
                              alt_url="https://arxiv.org/pdf/2401.00001"))
        session.add(ItemState(item_id=item.id, from_user=True, captured_via="slack"))
        session.commit()
        arxiv = item.id
    (tmp_path / "pdf_cache").mkdir()
    (tmp_path / "pdf_cache" / f"{arxiv}.pdf").write_bytes(PDF)

    assert store.move_from_caches(engine, tmp_path) == {"images": 0, "pdfs": 0}
    assert media_proxy.cache_get(tmp_path / "img_cache", URL) is not None
    assert (tmp_path / "pdf_cache" / f"{arxiv}.pdf").exists()


def test_a_picture_already_trimmed_from_the_cache_is_left_alone(tmp_path, engine) -> None:
    add_picture_item(engine)
    assert store.move_from_caches(engine, tmp_path) == {"images": 0, "pdfs": 0}


# ---- the notice for a missing picture ----------------------------------------------------------


def _picture_reader(engine, item_id: int) -> dict:
    """The reader block of a picture item, as the item route builds it."""
    with Session(engine) as session:
        doc = session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).one()
        return {"kind": "article", "html": doc.html, "lead_image": doc.lead_image,
                "source_url": doc.source_url}


def test_a_document_whose_picture_is_gone_shows_a_sentence_not_a_broken_image(tmp_path, engine) -> None:
    item_id = add_picture_item(engine)
    reader = _picture_reader(engine, item_id)
    shown = store.with_missing_picture_notice(reader, tmp_path, item_id)
    assert "<img" not in shown["html"] and "no longer stored" in shown["html"]
    assert shown["lead_image"] == ""
    store.put(tmp_path, item_id, PNG)
    assert store.with_missing_picture_notice(reader, tmp_path, item_id) == reader


def test_a_document_that_is_not_a_picture_is_never_changed(tmp_path) -> None:
    reader = {"kind": "article", "html": "<p>text</p><img src=\"https://cdn.example.org/a.png\">",
              "lead_image": "https://cdn.example.org/a.png", "source_url": "https://example.org/story"}
    assert store.with_missing_picture_notice(reader, tmp_path, 1) == reader
    assert store.with_missing_picture_notice(None, tmp_path, 1) is None


def test_a_picture_still_in_the_cache_is_not_reported_missing(tmp_path, engine) -> None:
    item_id = add_picture_item(engine)
    media_proxy.cache_put(tmp_path / "img_cache", URL, PNG, "image/png")
    reader = _picture_reader(engine, item_id)
    assert store.with_missing_picture_notice(reader, tmp_path, item_id) == reader
