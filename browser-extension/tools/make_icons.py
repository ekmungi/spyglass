"""Write the extension's icons (16, 32, 48 and 128 pixels) as PNG files, with no image library.

Each icon is a rounded square in a calm dark blue with a white lens-like ring and a short handle.
The shapes are drawn by testing every pixel against a few distance rules, with 4x4 samples per
pixel for smooth edges, and the PNG is written with `zlib` and `struct` only.

Run from anywhere:  python browser-extension/tools/make_icons.py
The result is committed (browser-extension/icons/), so the extension needs no build step.
"""

import math
import struct
import zlib
from pathlib import Path

SIZES = (16, 32, 48, 128)
BLUE = (35, 64, 107)  # the square
WHITE = (255, 255, 255)  # the ring and the handle
SAMPLES = 4  # samples per pixel edge (4 x 4 = 16 per pixel)


def inside_rounded_square(x: float, y: float, radius: float) -> bool:
    """Whether the point (x, y) of the unit square lies inside a square with rounded corners."""
    cx = min(max(x, radius), 1 - radius)
    cy = min(max(y, radius), 1 - radius)
    return math.hypot(x - cx, y - cy) <= radius


def on_lens(x: float, y: float) -> bool:
    """Whether the point lies on the white ring or on its handle (unit-square coordinates)."""
    ring_centre = (0.43, 0.43)
    distance = math.hypot(x - ring_centre[0], y - ring_centre[1])
    if 0.215 <= distance <= 0.305:
        return True
    # The handle: a thick line from the ring's lower right towards the corner.
    start, end = (0.65, 0.65), (0.82, 0.82)
    dx, dy = end[0] - start[0], end[1] - start[1]
    t = max(0.0, min(1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (start[0] + t * dx), y - (start[1] + t * dy)) <= 0.05


def pixel(column: int, row: int, size: int) -> tuple[int, int, int, int]:
    """The RGBA value of one pixel, averaged over SAMPLES x SAMPLES points."""
    covered = ink = 0
    for i in range(SAMPLES):
        for j in range(SAMPLES):
            x = (column + (i + 0.5) / SAMPLES) / size
            y = (row + (j + 0.5) / SAMPLES) / size
            if inside_rounded_square(x, y, 0.22):
                covered += 1
                ink += 1 if on_lens(x, y) else 0
    if covered == 0:
        return (0, 0, 0, 0)
    mix = ink / covered
    colour = tuple(round(BLUE[k] * (1 - mix) + WHITE[k] * mix) for k in range(3))
    return (*colour, round(255 * covered / (SAMPLES * SAMPLES)))


def chunk(kind: bytes, data: bytes) -> bytes:
    """One PNG chunk: length, type, data and the CRC of type and data."""
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(size: int) -> bytes:
    """A complete RGBA PNG image of `size` x `size` pixels."""
    rows = bytearray()
    for row in range(size):
        rows.append(0)  # filter type "none" for this scan line
        for column in range(size):
            rows.extend(pixel(column, row, size))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8 bit, colour type 6 (RGBA)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


def main() -> None:
    """Write icon-<size>.png for every size into the extension's icons folder."""
    folder = Path(__file__).resolve().parent.parent / "icons"
    folder.mkdir(exist_ok=True)
    for size in SIZES:
        (folder / f"icon-{size}.png").write_bytes(png_bytes(size))


if __name__ == "__main__":
    main()
