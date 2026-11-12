"""Tests for the text of the batch filing request (radar/filing_request.py)."""

from spyglass_service.radar.claude_bridge import ABOUT_HINT, MISSING_TOOLS_BATCH, STANDING_LINE
from spyglass_service.radar.filing_request import build_batch_request


def test_the_batch_request_counts_the_items_and_keeps_its_shape():
    text = build_batch_request(3, "http://127.0.0.1:7778")
    assert text.startswith("Spyglass: 3 items are waiting to be filed in this vault.")
    assert "spyglass-file skill" in text and "radar_filing_queue" in text
    assert text.rstrip().endswith(STANDING_LINE)
    assert build_batch_request(1, "http://127.0.0.1:7778").startswith(
        "Spyglass: 1 item is waiting")


def test_the_batch_request_names_the_sending_spyglass_and_forbids_a_hunt():
    text = build_batch_request(2, "http://127.0.0.1:7778")
    assert "This comes from the Spyglass running at http://127.0.0.1:7778." in text
    assert MISSING_TOOLS_BATCH == (
        "If the Spyglass tools are missing, or do not know these items, say so and stop. "
        "Do not look for Spyglass's files or database.")
    assert MISSING_TOOLS_BATCH in text and ABOUT_HINT in text
    assert text.index("This comes from") < text.index("Please file them")
    assert text.index(MISSING_TOOLS_BATCH) < text.index(STANDING_LINE)
    assert "Secret" not in text and len(text) < 1200
