"""Make installer/spyglass.ico from the browser extension's 128-pixel icon.

The installer, its Start-menu entry and the tray all use this icon. Run it again only when the
extension's icon changes: `uv run python installer/make_icon.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "browser-extension" / "icons" / "icon-128.png"
TARGET = HERE / "spyglass.ico"
# The sizes Windows asks for: the tray and small lists (16), the taskbar (32), the Start menu
# and Explorer (48), and large tiles and the installer's own file (256).
ICON_SIZES = (16, 32, 48, 256)


def make_icon(source: Path, target: Path) -> None:
    """Write `target` as a Windows icon holding every size in ICON_SIZES, drawn from `source`.

    Pillow leaves out any size larger than the image it saves, so the image is first scaled up
    to the largest size; the smaller sizes are then scaled down from it.
    """
    largest = max(ICON_SIZES)
    with Image.open(source) as image:
        base = image.convert("RGBA").resize((largest, largest), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    base.save(target, format="ICO", sizes=[(size, size) for size in ICON_SIZES])


def main() -> int:
    """Make the icon from the extension's icon and say where it went."""
    make_icon(SOURCE, TARGET)
    print(f"Wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
