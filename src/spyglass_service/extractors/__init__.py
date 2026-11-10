"""Content extractors: turn raw acquired bytes/HTML into clean text.

Each module is a pure, injectable-seam extractor for one content kind (html, pdf,
transcript). The conductor (documents.fetch_fulltext) dispatches to the right one
based on what the acquire layer returned; later tasks (PyMuPDF, vision-LLM OCR) add
extractors here without touching the conductor's routing logic.
"""
