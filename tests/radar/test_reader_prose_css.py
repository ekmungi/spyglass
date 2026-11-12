"""The reader's document container must contain whatever a page's markup tries to draw."""

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "radar" / "reader" / "reader.css"


def prose_rule() -> str:
    """The declarations of the rule whose selector is exactly `.r-prose`."""
    match = re.search(r"^\.r-prose\s*\{([^}]*)\}", CSS.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else ""


def test_prose_clips_descendants_and_anchors_fixed_children_inside_itself() -> None:
    rule = prose_rule()
    assert re.search(r"contain:\s*paint", rule)
    assert re.search(r"position:\s*relative", rule)
    assert re.search(r"overflow-x:\s*clip", rule)
