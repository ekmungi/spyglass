"""Full-text content store: read and write an item's stored markdown.

The full text of the document behind a card lives in the SQLite DB (the Content
table), not as vault files. This module is the single read/write path for it.
"""

from datetime import UTC, datetime

from sqlalchemy import Engine, text
from sqlmodel import Session, select

from spyglass_service.models import Content


def _sanitize(text_value: str | None) -> str | None:
    """Strip unpaired UTF-16 surrogates that SQLite's UTF-8 encoder rejects.

    Fetched pages occasionally decode into lone surrogates (seen live on card 1155), which
    crash the INSERT with `UnicodeEncodeError: surrogates not allowed`. Round-tripping through
    UTF-8 with errors="replace" swaps each bad code unit for U+FFFD and leaves clean text as-is.

    Args:
        text_value: The string to sanitize, or None.

    Returns:
        The sanitized string, or None when the input was None.
    """
    if text_value is None:
        return None
    return text_value.encode("utf-8", errors="replace").decode("utf-8")


def store_fulltext(
    engine: Engine,
    *,
    item_id: int,
    markdown: str,
    source_url: str | None = None,
    content_type: str | None = None,
    status: str = "ok",
    error: str | None = None,
    detected_type: str | None = None,
    tier_reached: str | None = None,
    http_status: int | None = None,
    error_class: str | None = None,
) -> None:
    """Upsert an item's stored full text (1:1 with the item).

    text_chars is computed from the markdown. Re-storing replaces in place so each
    item keeps exactly one content row. A failed/empty fetch is recorded via status.
    Markdown and error are sanitized first (lone surrogates crash SQLite).

    detected_type/tier_reached/http_status/error_class are
    the structured, card-visible failure record documents.fetch_fulltext composes (via
    fetch_failure.py) on both success and failure -- all default None so every caller
    that predates these fields (or a lane that never touches the acquire ladder) is unaffected.
    The two string fields are sanitized the same way as markdown/error.
    """
    markdown = _sanitize(markdown)
    error = _sanitize(error)
    detected_type = _sanitize(detected_type)
    error_class = _sanitize(error_class)
    with Session(engine) as session:
        row = session.exec(select(Content).where(Content.item_id == item_id)).first()
        if row is None:
            row = Content(item_id=item_id, markdown=markdown)
        row.markdown = markdown
        row.text_chars = len(markdown)
        row.source_url = source_url
        row.content_type = content_type
        row.status = status
        row.error = error
        row.detected_type = detected_type
        row.tier_reached = tier_reached
        row.http_status = http_status
        row.error_class = error_class
        row.fetched_at = datetime.now(UTC)
        session.add(row)
        # Keep the FTS index in sync: drop the old body, index the new one (if any).
        conn = session.connection()
        conn.execute(text("DELETE FROM content_fts WHERE item_id = :iid"), {"iid": item_id})
        if markdown:
            conn.execute(
                text("INSERT INTO content_fts (body, item_id) VALUES (:body, :iid)"),
                {"body": markdown, "iid": item_id},
            )
        session.commit()


def delete_content(engine: Engine, item_id: int) -> None:
    """Hard-delete an item's stored full text and its FTS index entry.

    Removes the content_fts row first (virtual table), then the Content row.
    Idempotent: a no-op when nothing is stored for this item.
    """
    with Session(engine) as session:
        conn = session.connection()
        conn.execute(text("DELETE FROM content_fts WHERE item_id = :iid"), {"iid": item_id})
        row = session.exec(select(Content).where(Content.item_id == item_id)).first()
        if row is not None:
            session.delete(row)
        session.commit()


def get_fulltext(engine: Engine, item_id: int) -> dict | None:
    """Return the stored content as a dict, or None if nothing is stored yet."""
    with Session(engine) as session:
        row = session.exec(select(Content).where(Content.item_id == item_id)).first()
        if row is None:
            return None
        return {
            "item_id": row.item_id,
            "markdown": row.markdown,
            "text_chars": row.text_chars,
            "source_url": row.source_url,
            "content_type": row.content_type,
            "status": row.status,
            "error": row.error,
            "detected_type": row.detected_type,
            "tier_reached": row.tier_reached,
            "http_status": row.http_status,
            "error_class": row.error_class,
            "fetched_at": row.fetched_at.isoformat(),
        }


def _fts_query(query: str) -> str:
    """Turn user text into a safe FTS5 MATCH expression (AND of quoted terms)."""
    return " ".join(f'"{term}"' for term in query.split())


def search_fulltext(engine: Engine, query: str, limit: int = 50) -> list[dict]:
    """Search stored full text (FTS5) UNION title/summary/origin/source/url for all items.

    Returns [{item_id, snippet}]. Items with stored content are matched on their body
    (with a highlighted snippet, ranked first); the metadata match (title, summary,
    origin, source, url) runs for EVERY item -- not only content-less ones --
    so a card with stored full text is still found by a title/source/url match, e.g.
    a YouTube card whose transcript never says "bio" but whose title does. Results are
    unioned and deduped by item_id, full-text hits first.
    """
    q = query.strip()
    if not q:
        return []
    results: list[dict] = []
    seen: set[int] = set()
    with Session(engine) as session:
        conn = session.connection()
        matched = conn.execute(
            text(
                "SELECT item_id, snippet(content_fts, 0, '[', ']', '...', 12) AS snip "
                "FROM content_fts WHERE content_fts MATCH :q ORDER BY rank LIMIT :lim"
            ),
            {"q": _fts_query(q), "lim": limit},
        ).all()
        for item_id, snip in matched:
            results.append({"item_id": item_id, "snippet": snip})
            seen.add(item_id)

        # Metadata match: search title/summary/origin/source/url for EVERY card (not only
        # content-less ones), unioned with the FTS body hits above. Multi-term: each whitespace term
        # must appear in at least one field (AND across terms), so "bio youtube" matches a card whose
        # title has "bio" and whose url has "youtube". Field names are hardcoded (no injection); only
        # the term values are bound parameters.
        terms = [t for t in q.lower().split() if t]
        if terms:
            fields = [
                "lower(title)",
                "lower(coalesce(summary, ''))",
                "lower(coalesce(origin, ''))",
                "lower(source)",
                "lower(url)",
            ]
            params: dict[str, object] = {"lim": limit}
            clauses: list[str] = []
            for i, term in enumerate(terms):
                params[f"t{i}"] = f"%{term}%"
                ors = " OR ".join(f"{field} LIKE :t{i}" for field in fields)
                clauses.append(f"({ors})")
            where = " AND ".join(clauses)
            meta = conn.execute(
                text(f"SELECT id, title, summary FROM item WHERE {where} LIMIT :lim"),  # noqa: S608
                params,
            ).all()
            for item_id, title, summary in meta:
                if item_id in seen:
                    continue
                results.append({"item_id": item_id, "snippet": (title or summary or "")[:160]})
                seen.add(item_id)
    return results

