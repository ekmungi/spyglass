"""Tests for scripts/make_icons.py, which renders every Spyglass icon file from the SVG master.

The master in assets/icon/ is the only drawing of the icon. The script turns it into the Windows
icon (installer, Start menu, launcher, tray), the browser extension's PNGs and the web favicon, so
these tests pin the colours, the sizes, the small master used at 16 to 24 pixels, and that the
committed files are exactly what the script renders today.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

from spyglass_service.desktop import tray

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_icons.py"
ICON_DIR = ROOT / "assets" / "icon"
CHARCOAL = (0x23, 0x26, 0x2E)
GOLD = (0xFF, 0xC9, 0x4D)
SPEC_FILLS = ["#23262E", "#D9603B", "#2A9D8F", "#FFF4E0", "#FFC94D", "#FFC94D"]
ICO_SIZES = {16, 20, 24, 32, 40, 48, 64, 256}
EXTENSION_SIZES = (16, 32, 48, 128)
# Every file the script writes, relative to the repository root.
OUTPUTS = [
    Path("installer/spyglass.ico"),
    *(Path(f"browser-extension/icons/icon-{size}.png") for size in EXTENSION_SIZES),
    Path("frontend/public/favicon.svg"),
]
SVG_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'


@pytest.fixture(scope="module")
def icons():
    """Import scripts/make_icons.py, which is a script and not part of the package."""
    spec = importlib.util.spec_from_file_location("spyglass_make_icons", SCRIPT)
    assert spec and spec.loader, "scripts/make_icons.py is missing"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def master(icons):
    """The parsed master drawing, with the spark."""
    return icons.parse_svg((ICON_DIR / "spyglass.svg").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def small(icons):
    """The parsed small master, without the spark."""
    return icons.parse_svg((ICON_DIR / "spyglass-small.svg").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(icons, tmp_path_factory) -> Path:
    """A scratch repository root holding only the masters, after one run of the generator."""
    root = tmp_path_factory.mktemp("icon-root")
    shutil.copytree(ICON_DIR, root / "assets" / "icon")
    icons.build_all(root)
    return root


def _near(pixel: tuple[int, ...], colour: tuple[int, int, int], tolerance: int) -> bool:
    """Whether every colour channel of `pixel` lies within `tolerance` of `colour`."""
    return all(abs(pixel[i] - colour[i]) <= tolerance for i in range(3))


def _centroid(points) -> tuple[float, float]:
    """The average of a shape's points, which is its centre for a symmetric rounded rectangle."""
    return (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points))


# --- the masters and the parser ---------------------------------------------------------------


def test_master_has_the_spec_colours_in_order(master) -> None:
    """Tile, eyepiece, middle tube, barrel, lens ring and spark, in the spec's colours."""
    assert master.size == 128
    assert [shape.fill for shape in master.shapes] == SPEC_FILLS


def test_small_master_is_the_master_without_the_spark(master, small) -> None:
    """The small master draws everything but the spark, which would be a stray speck at 16 px."""
    assert small.shapes == master.shapes[:-1]


def test_rotation_is_applied_counter_clockwise(master) -> None:
    """The lens ring's centre (102, 64) turns -35 degrees about (64, 64), up and to the right."""
    x, y = _centroid(master.shapes[4].points)
    angle = math.radians(-35)
    assert x == pytest.approx(64 + 38 * math.cos(angle), abs=0.01)
    assert y == pytest.approx(64 + 38 * math.sin(angle), abs=0.01)


def test_spark_is_not_rotated(master) -> None:
    """The spark sits outside the rotated group, so its points are the path's own."""
    assert master.shapes[5].points[0] == (107.0, 11.0)


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ('<circle cx="10" cy="10" r="4" fill="#000"/>', "circle"),
        ('<g transform="translate(1 2)"><rect width="4" height="4" fill="#000"/></g>', "translate"),
        ('<path d="M0 0 C1 1 2 2 3 3 Z" fill="#000"/>', "'C'"),
        ('<path d="M0 0 L10 - 0 L10 10 Z" fill="#000"/>', "'-'"),
        ('<rect width="4" height="4" fill="#000" stroke="#fff"/>', "stroke"),
        ('<rect width="4" height="4" fill="#000" transform="rotate(5)"/>', "transform"),
        ('<rect width="4" height="4" fill="red"/>', "red"),
    ],
)
def test_unknown_svg_features_are_refused(icons, body: str, named: str) -> None:
    """An edited master that uses a feature the parser does not know stops with a clear error."""
    with pytest.raises(ValueError, match=named):
        icons.parse_svg(f"{SVG_HEAD}{body}</svg>")


# --- the renderer ------------------------------------------------------------------------------


def test_render_has_the_asked_size(icons, master) -> None:
    """A render is a square RGBA image of the size asked for."""
    image = icons.render(master, 48)
    assert image.mode == "RGBA"
    assert image.size == (48, 48)


def test_16px_tile_corner_is_charcoal_and_centre_is_not(icons, small) -> None:
    """At 16 pixels the empty top-left of the tile is charcoal and the telescope fills the centre."""
    image = icons.render(small, 16)
    corner = image.getpixel((3, 3))
    assert corner[3] == 255
    assert _near(corner, CHARCOAL, 12)
    assert not _near(image.getpixel((8, 8)), CHARCOAL, 40)


def test_corner_outside_the_rounded_tile_is_transparent(icons, master) -> None:
    """The tile's rounded corners leave the image's own corners clear."""
    assert icons.render(master, 64).getpixel((0, 0))[3] == 0


def test_256px_shows_the_gold_spark(icons, master) -> None:
    """The spark's centre, (107, 21) in the master, is gold at 256 pixels."""
    assert _near(icons.render(master, 256).getpixel((214, 42)), GOLD, 12)


# --- the files the generator writes ------------------------------------------------------------


def test_ico_holds_every_size(built: Path) -> None:
    """The Windows icon carries every size the shell, the tray and the installer ask for."""
    with Image.open(built / "installer" / "spyglass.ico") as icon:
        assert set(icon.info["sizes"]) == {(size, size) for size in ICO_SIZES}


def test_ico_frames_are_rendered_at_their_own_size(icons, master, small, built: Path) -> None:
    """The small sizes come from the small master, the others from the master, none downscaled."""
    with Image.open(built / "installer" / "spyglass.ico") as icon:
        for size in sorted(ICO_SIZES):
            drawing = small if size <= 24 else master
            frame = icon.ico.getimage((size, size)).convert("RGBA")
            assert frame.tobytes() == icons.render(drawing, size).tobytes(), size


def test_extension_pngs_have_their_sizes(icons, small, built: Path) -> None:
    """Each extension icon has its size, and the 16-pixel one comes from the small master."""
    for size in EXTENSION_SIZES:
        with Image.open(built / "browser-extension" / "icons" / f"icon-{size}.png") as image:
            assert image.size == (size, size)
            if size == 16:
                assert image.convert("RGBA").tobytes() == icons.render(small, 16).tobytes()


def test_favicon_is_the_master(built: Path) -> None:
    """The browser tab shows the master SVG itself."""
    favicon = built / "frontend" / "public" / "favicon.svg"
    assert favicon.read_bytes() == (ICON_DIR / "spyglass.svg").read_bytes()


def test_build_twice_gives_identical_files(icons, built: Path) -> None:
    """A second run writes byte-identical files, so a rebuild never shows up as a change."""

    def digests() -> dict[Path, str]:
        return {rel: hashlib.sha256((built / rel).read_bytes()).hexdigest() for rel in OUTPUTS}

    before = digests()
    written = icons.build_all(built)
    assert sorted(written) == sorted(built / rel for rel in OUTPUTS)
    assert digests() == before


def _pictures(path: Path) -> dict[tuple[int, int], bytes]:
    """The decoded RGBA pixels of each image in a PNG or ICO file, keyed by size.

    Pixels rather than file bytes, because another zlib build may compress the same picture
    differently, and the question is whether the committed picture is current.
    """
    with Image.open(path) as image:
        if image.format != "ICO":
            return {image.size: image.convert("RGBA").tobytes()}
        return {size: image.ico.getimage(size).convert("RGBA").tobytes() for size in image.info["sizes"]}


def test_committed_files_match_the_generator(built: Path) -> None:
    """The icon files in the repository are what the generator renders from today's master."""
    for rel in OUTPUTS:
        stale = f"{rel} is stale: run scripts/make_icons.py"
        if rel.suffix == ".svg":
            assert (ROOT / rel).read_bytes() == (built / rel).read_bytes(), stale
        else:
            assert _pictures(ROOT / rel) == _pictures(built / rel), stale


@pytest.mark.parametrize("missing", ["spyglass.svg", "spyglass-small.svg"])
def test_build_refuses_a_root_without_a_master(icons, tmp_path: Path, missing: str) -> None:
    """Pointed at a folder without one of the masters, the generator stops and names that file."""
    shutil.copytree(ICON_DIR, tmp_path / "assets" / "icon")
    (tmp_path / "assets" / "icon" / missing).unlink()
    with pytest.raises(FileNotFoundError, match=missing):
        icons.build_all(tmp_path)
    assert not (tmp_path / "installer").exists()


def test_tray_finds_the_icon() -> None:
    """The tray reads installer/spyglass.ico, which holds its 16 and 32 pixel sizes."""
    assert tray.ICON_PATH.is_file()
    with Image.open(tray.ICON_PATH) as icon:
        assert {(16, 16), (32, 32)} <= set(icon.info["sizes"])


# --- the browser tab ---------------------------------------------------------------------------


def test_index_html_links_the_favicon() -> None:
    """The interface's HTML points the browser at the favicon the generator writes."""
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />' in html
