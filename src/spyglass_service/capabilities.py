"""Which optional parts this install has: full PDF reading (PyMuPDF) and the local AI model.

Setup lets the user leave both out. Without PyMuPDF, PDFs are read with pypdf, which is always
installed; without fastembed, nothing can be embedded, so search by meaning and similar items
are off. The Settings page shows what is missing and how to add it.
"""

from __future__ import annotations

import importlib.util

# How the user adds a part later: setup's own Change button, or running setup again.
_HOW_TO_ADD = ("To add it, open Settings > Apps > Installed apps in Windows, choose Spyglass, then "
               "Modify, and tick {part}. Running Spyglass setup again does the same.")


class LocalModelMissing(RuntimeError):
    """Raised when something has to be embedded but the local AI model is not installed."""

    def __init__(self, message: str = "") -> None:
        """Default to the sentence the interface shows."""
        super().__init__(message or (
            "The local AI model is not installed, so this part of Spyglass is off. "
            + _HOW_TO_ADD.format(part="Local AI model")))


def _importable(*names: str) -> bool:
    """True when any of `names` can be imported; a blocked or broken entry counts as absent."""
    for name in names:
        try:
            if importlib.util.find_spec(name) is not None:
                return True
        except (ImportError, ValueError):
            continue
    return False


def pdf_reading_full() -> bool:
    """Whether PyMuPDF is installed (it imports as `fitz` or as `pymupdf`)."""
    return _importable("fitz", "pymupdf")


def local_ai_installed() -> bool:
    """Whether the embedding library behind the local AI model is installed."""
    return _importable("fastembed")


def report() -> dict:
    """What the Settings page shows: the PDF reading level, the model, and each missing part."""
    pdf_full = pdf_reading_full()
    local_ai = local_ai_installed()
    missing = []
    if not pdf_full:
        missing.append({
            "id": "pdf",
            "name": "PDF reading",
            "effect": ("PDF reading is basic: Spyglass reads the text of a PDF but may miss parts "
                       "of complex layouts."),
            "how_to_add": _HOW_TO_ADD.format(part="PDF reading"),
        })
    if not local_ai:
        missing.append({
            "id": "local-ai",
            "name": "Local AI model",
            "effect": ("Search by meaning, similar items and related items are off; search by "
                       "words still works."),
            "how_to_add": _HOW_TO_ADD.format(part="Local AI model"),
        })
    return {"pdf_reading": "full" if pdf_full else "basic", "local_ai": local_ai,
            "missing": missing}
