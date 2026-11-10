"""Enrichment prompt contract: schema, message builder, and result parsing.

The LLM is stateless; the user's relevance context is the interest statement, injected as
text into the system message (the stable, cache-friendly prefix). The same contract serves
Gate 1 (blurb) and Gate 2 (full text); `full` only changes the user-message framing.
"""

from dataclasses import dataclass, field


def _categories_line(categories: list[str] | None) -> str:
    """The category instruction shown to the model.

    Closed vocabulary: the model may ONLY pick from the user's managed set,
    never coin a new label. With no categories configured, everything is Unsorted.
    """
    if categories:
        listed = " | ".join(categories)
        return (
            "category + fits: choose `category` ONLY from this exact list -- "
            f"[{listed}]. Pick the single best fit; if none clearly fits, set `fits` false and "
            "leave `category` null. NEVER invent a new category or reword one of these."
        )
    return (
        "category + fits: there are no categories configured, so set `fits` false and leave "
        "`category` null (the item stays Unsorted)."
    )


_SYSTEM = (
    "You triage articles for a single user. Judge relevance ONLY against the user's interest "
    "statement below; you have no other knowledge of them. Return strict JSON matching the schema.\n"
    "- relevance_score: 0-100, how well the article matches the interests.\n"
    "- relevance_reason: one short line.\n"
    "- summary: a markdown summary of the article, about 350-400 characters (max ~450) -- enough to "
    "convey the core finding and why it matters.\n"
    "- tags: 3-6 short topical tags.\n"
    "- {categories_line}\n"
    "- confidence: 0.0-1.0 in your own judgment.\n\n"
    "USER INTEREST STATEMENT:\n{interest}"
)


def enrich_schema(categories: list[str] | None = None) -> dict:
    """Build the enrichment structured-output schema, constraining `category` to the managed set.

    When categories are given, `category` is an enum over exactly that set plus null -- the hard
    gate that stops the LLM coining near-duplicate labels. With no categories, only null
    is permitted (everything Unsorted).

    Args:
        categories: The user's managed category names (empty/None -> null-only).

    Returns:
        A structured-output schema dict for the OpenRouter JSON contract.
    """
    category_field = {"enum": [*(categories or []), None]}
    return {
        "name": "enrichment",
        "schema": {
            "type": "object",
            "properties": {
                "relevance_score": {"type": "integer"},
                "relevance_reason": {"type": "string"},
                "summary": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "category": category_field,
                "fits": {"type": "boolean"},
                "confidence": {"type": "number"},
            },
            "required": [
                "relevance_score", "relevance_reason", "summary", "tags", "fits", "confidence",
            ],
        },
    }


# Back-compat default (free-text category); real calls pass enrich_schema(categories).
ENRICH_SCHEMA = {
    "name": "enrichment",
    "schema": {
        "type": "object",
        "properties": {
            "relevance_score": {"type": "integer"},
            "relevance_reason": {"type": "string"},
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "category": {"type": ["string", "null"]},
            "fits": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": ["relevance_score", "relevance_reason", "summary", "tags", "fits", "confidence"],
    },
}


@dataclass(frozen=True)
class EnrichmentResult:
    """One parsed enrichment from the LLM. category is None when fits is false."""

    relevance_score: int
    relevance_reason: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    fits: bool = False
    confidence: float = 0.0


def build_messages(
    interest: str, title: str, body: str, *, full: bool, categories: list[str] | None = None
) -> list[dict]:
    """Build the chat messages, interest statement first (cacheable), article last.

    full=True frames `body` as the article's full text; full=False frames it as a short blurb
    (Gate 1). The system message carries the interest statement so the prefix stays stable
    across the batch for DeepSeek implicit caching, and lists the managed category set so the
    model picks from it.

    Args:
        interest: The user's interest statement (injected into the stable system prefix).
        title: Article title.
        body: Article body text or blurb.
        full: When True, frames the user message as full text; when False, as blurb.
        categories: The user's managed category names, listed for the model (closed vocabulary).

    Returns:
        A two-element list: [system message dict, user message dict].
    """
    kind = "full text" if full else "title and short blurb"
    user = f"Article ({kind}).\nTITLE: {title}\n\n{body}"
    system = _SYSTEM.format(
        interest=interest or "(none provided)", categories_line=_categories_line(categories)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_enrichment(raw: dict, allowed: set[str] | None = None) -> EnrichmentResult:
    """Parse + defensively clamp the model's JSON into an EnrichmentResult.

    Args:
        raw: The raw dict returned by the LLM (parsed from JSON).
        allowed: When given, the closed set of category names; any category outside it is mapped
            to None (Unsorted). This is the post-validation backstop for the schema enum:
            even a model that ignores the enum can never write a label the user has not defined.

    Returns:
        An EnrichmentResult with all fields validated and clamped.
        - relevance_score is clamped to [0, 100].
        - Missing fields default to empty/false values.
        - category is forced to None when fits is false, or when it is not in `allowed`.
    """
    score = max(0, min(100, int(raw.get("relevance_score", 0))))
    fits = bool(raw.get("fits", False))
    category = (raw.get("category") or None) if fits else None
    if allowed is not None and category not in allowed:
        category = None
    return EnrichmentResult(
        relevance_score=score,
        relevance_reason=str(raw.get("relevance_reason", "")),
        summary=str(raw.get("summary", "")),
        tags=[str(t) for t in raw.get("tags", []) or []],
        category=category,
        fits=fits,
        confidence=float(raw.get("confidence", 0.0) or 0.0),
    )


def bucket_from_score(score: int) -> str:
    """Map a 0-100 relevance score to the legacy bucket label used in the UI.

    Args:
        score: Integer relevance score in the range [0, 100].

    Returns:
        One of "high" (>=70), "medium" (>=40), "low" (>=15), or "out" (<15).
    """
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 15:
        return "low"
    return "out"
