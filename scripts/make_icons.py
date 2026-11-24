"""Render every Spyglass icon file from the SVG master in assets/icon/.

Writes installer/spyglass.ico (the installer, the Start menu, Spyglass.exe and the tray), the
browser extension's PNG icons and frontend/public/favicon.svg (the browser tab). Run it after
changing a master; the output is committed, so building Spyglass needs no drawing step:

    uv run python scripts/make_icons.py

Pillow cannot read SVG, so this script reads the few SVG features the masters use (a square
viewBox, rect, g with rotate, and paths of straight lines), turns every shape into a polygon with
its rotation applied, draws it at eight times the target size and scales it down. Any other SVG
feature stops the script with an error, so an edited master never renders silently wrong.
"""

from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

SVG_NS = "{http://www.w3.org/2000/svg}"
MASTER = Path("assets/icon/spyglass.svg")
SMALL_MASTER = Path("assets/icon/spyglass-small.svg")
ICO_PATH = Path("installer/spyglass.ico")
EXTENSION_ICONS = Path("browser-extension/icons")
FAVICON_PATH = Path("frontend/public/favicon.svg")
# The sizes Windows asks for: small lists and the tray at 100, 125 and 150 percent scaling (16,
# 20, 24), the taskbar and Start menu (32, 40, 48), Explorer's larger views (64) and tiles (256).
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
EXTENSION_SIZES = (16, 32, 48, 128)
# At this size and below the spark becomes a stray speck, so the small master (no spark) is used.
SMALL_LIMIT = 24
# Shapes are drawn at this many times the target size and scaled down, for smooth edges. Pillow
# fills a polygon one drawing pixel wider than its outline, so 16 rather than 8 halves that error;
# compared with a browser's own rendering of the master, 16 matched best at 16, 32 and 256 pixels.
SUPERSAMPLE = 16
# The scale-down averages each block of SUPERSAMPLE x SUPERSAMPLE pixels. Lanczos, the other
# candidate, left a dark halo around the light shapes at 16 and 32 pixels.
DOWNSCALE = Image.Resampling.BOX
# Points along each rounded corner's quarter circle; 32 keeps the curve within a third of a drawing
# pixel of the true arc even on the 4,096-pixel canvas of the 256-pixel icon.
ROUNDING_STEPS = 32
# The only attributes each element may carry; anything else would be drawn wrongly or not at all.
ALLOWED_ATTRIBUTES = {
    "svg": {"viewBox", "width", "height"},
    "g": {"transform"},
    "rect": {"x", "y", "width", "height", "rx", "fill"},
    "path": {"d", "fill"},
}
ROTATE = re.compile(r"^\s*rotate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+)[\s,]+(-?[\d.]+))?\s*\)\s*$")
COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d*\.?\d+")
PATH_SEPARATORS = re.compile(r"[\s,]+")

Point = tuple[float, float]
Transform = Callable[[Point], Point]


@dataclass(frozen=True)
class Shape:
    """One filled outline in master coordinates, with every rotation already applied."""

    points: tuple[Point, ...]
    fill: str


@dataclass(frozen=True)
class Drawing:
    """A parsed master: the side of its square viewBox and its shapes in painting order."""

    size: float
    shapes: tuple[Shape, ...]


def parse_svg(text: str) -> Drawing:
    """Read a master's SVG text into a Drawing; raise ValueError on any feature not supported."""
    # The only input is the repository's own masters, and the standard library's expat parser
    # neither fetches external entities nor expands nested ones without limit.
    root = ET.fromstring(text)
    if root.tag != f"{SVG_NS}svg":
        raise ValueError(f"the icon master must be an SVG document, not <{root.tag}>")
    _check_attributes(root, "svg")
    return Drawing(_square_viewbox(root.get("viewBox", "")), tuple(_shapes(root, lambda point: point)))


def _check_attributes(element: ET.Element, tag: str) -> None:
    """Raise ValueError when `element` carries an attribute the generator would ignore."""
    unknown = sorted(set(element.attrib) - ALLOWED_ATTRIBUTES[tag])
    if unknown:
        raise ValueError(f"the icon generator does not understand {unknown} on <{tag}>")


def _square_viewbox(value: str) -> float:
    """The side of a square viewBox that starts at 0 0; raise ValueError for any other viewBox."""
    numbers = [float(number) for number in value.replace(",", " ").split()]
    if len(numbers) != 4 or numbers[0] or numbers[1] or numbers[2] != numbers[3]:
        raise ValueError(f"the icon master needs a square viewBox starting at 0 0, not {value!r}")
    return numbers[2]


def _shapes(parent: ET.Element, transform: Transform) -> Iterator[Shape]:
    """Yield the shapes under `parent` in painting order, each moved by `transform`."""
    for element in parent:
        tag = element.tag.removeprefix(SVG_NS)
        if tag not in ALLOWED_ATTRIBUTES or tag == "svg":
            raise ValueError(f"the icon generator cannot draw <{tag}>")
        _check_attributes(element, tag)
        if tag == "g":
            inner = _rotation(element.get("transform"))
            yield from _shapes(element, lambda point, inner=inner: transform(inner(point)))
            continue
        outline = _rounded_rect(element) if tag == "rect" else _polygon(element.get("d", ""))
        yield Shape(tuple(transform(point) for point in outline), _fill(element))


def _rotation(value: str | None) -> Transform:
    """The point mapping for a group's `rotate(angle [cx cy])`, in SVG's y-down coordinates."""
    if value is None:
        return lambda point: point
    match = ROTATE.match(value)
    if match is None:
        raise ValueError(f"the icon generator only understands rotate(...), not {value!r}")
    angle = math.radians(float(match[1]))
    cx, cy = float(match[2] or 0), float(match[3] or 0)
    cos, sin = math.cos(angle), math.sin(angle)
    return lambda point: (
        cx + (point[0] - cx) * cos - (point[1] - cy) * sin,
        cy + (point[0] - cx) * sin + (point[1] - cy) * cos,
    )


def _number(element: ET.Element, name: str, default: float | None = None) -> float:
    """A numeric attribute of `element`; raise ValueError when a required one is missing."""
    value = element.get(name)
    if value is None:
        if default is None:
            raise ValueError(f"<rect> needs a {name} attribute")
        return default
    return float(value)


def _rounded_rect(element: ET.Element) -> list[Point]:
    """The outline of a rect, each rounded corner traced as a quarter circle, clockwise on screen."""
    x, y = _number(element, "x", 0.0), _number(element, "y", 0.0)
    width, height = _number(element, "width"), _number(element, "height")
    radius = min(_number(element, "rx", 0.0), width / 2, height / 2)
    # Corner centres with the angle each arc starts at (y points down, so -90 degrees is "up").
    corners = (
        (x + width - radius, y + radius, -90.0),
        (x + width - radius, y + height - radius, 0.0),
        (x + radius, y + height - radius, 90.0),
        (x + radius, y + radius, 180.0),
    )
    points = []
    for cx, cy, start in corners:
        for step in range(ROUNDING_STEPS + 1):
            angle = math.radians(start + 90 * step / ROUNDING_STEPS)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _polygon(d: str) -> list[Point]:
    """The points of a path made of one absolute M, then L commands, closed with Z."""
    leftover = PATH_SEPARATORS.sub("", PATH_TOKEN.sub("", d))
    if leftover:
        raise ValueError(f"the icon generator cannot read {leftover[0]!r} in the path {d!r}")
    tokens = PATH_TOKEN.findall(d)
    if not tokens or tokens[0] != "M":
        raise ValueError(f"the icon generator only draws paths that start with M, not {d!r}")
    numbers: list[float] = []
    for token in tokens[1:]:
        if token in ("L", "Z"):
            continue
        if token.isalpha():
            raise ValueError(f"the icon generator only draws paths made of M, L and Z, not {token!r}")
        numbers.append(float(token))
    if len(numbers) % 2 or len(numbers) < 6:
        raise ValueError(f"a path needs at least three x y pairs, not {d!r}")
    return list(zip(numbers[0::2], numbers[1::2], strict=True))


def _fill(element: ET.Element) -> str:
    """The `#RRGGBB` fill of a shape; raise ValueError for any other colour form."""
    fill = element.get("fill", "")
    if not COLOUR.match(fill):
        raise ValueError(f"the icon generator needs fills written as #RRGGBB, not {fill!r}")
    return fill


def render(drawing: Drawing, size: int) -> Image.Image:
    """Draw `drawing` as a `size` by `size` RGBA image: at SUPERSAMPLE times, then averaged down."""
    canvas = size * SUPERSAMPLE
    scale = canvas / drawing.size
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    for shape in drawing.shapes:
        # No half-pixel shift: Pillow fills from the floor of each edge to the floor of the other,
        # so unshifted outlines spread its extra drawing pixel evenly over both sides.
        pen.polygon([(x * scale, y * scale) for x, y in shape.points], fill=shape.fill)
    return image.resize((size, size), DOWNSCALE)


def build_all(root: Path) -> list[Path]:
    """Render every icon file under the repository folder `root` and return the paths written."""
    for master in (MASTER, SMALL_MASTER):
        if not (root / master).is_file():
            raise FileNotFoundError(f"icon master not found: {root / master}")
    full = parse_svg((root / MASTER).read_text(encoding="utf-8"))
    small = parse_svg((root / SMALL_MASTER).read_text(encoding="utf-8"))

    def picture(size: int) -> Image.Image:
        """The render for one size, from the small master at SMALL_LIMIT pixels and below."""
        return render(small if size <= SMALL_LIMIT else full, size)

    written = [_write_ico(root / ICO_PATH, [picture(size) for size in ICO_SIZES])]
    for size in EXTENSION_SIZES:
        target = root / EXTENSION_ICONS / f"icon-{size}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        picture(size).save(target, format="PNG")
        written.append(target)
    favicon = root / FAVICON_PATH
    favicon.parent.mkdir(parents=True, exist_ok=True)
    favicon.write_bytes((root / MASTER).read_bytes())
    written.append(favicon)
    return written


def _write_ico(target: Path, frames: list[Image.Image]) -> Path:
    """Save `frames` (one per ICO_SIZES entry, smallest first) as one Windows icon file.

    Pillow keeps only sizes no larger than the image it saves, so the largest frame is saved and
    the others are handed over whole, which stops Pillow from scaling the largest one down.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    largest = frames[-1]
    largest.save(target, format="ICO", sizes=[frame.size for frame in frames], append_images=frames[:-1])
    return target


def main() -> int:
    """Render every icon file in this repository and list what was written."""
    root = Path(__file__).resolve().parents[1]
    for path in build_all(root):
        print(f"Wrote {path.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
