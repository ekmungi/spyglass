"""LLM category re-classification contract.

Files a card into one of the user's chosen categories -- or leaves it Unsorted (null) -- via an
enum-constrained structured-output call. This is the SAME closed-vocabulary guarantee as new-item
enrichment (enrich_prompt), applied to the backlog over each card's stored summary (no re-fetch).

Why the LLM and not the embedder: calibration proved arctic embeddings do not separate the user's
intent-based categories -- they cut across topical similarity (a clinical-LLM paper embeds near
other LLM papers, not near a surgical-robot paper, though both are "Healthcare AI"). Only the LLM,
which reads what the article is about and its application, can map onto that taxonomy.
"""

from collections.abc import Callable

from spyglass_service.openrouter import chat_json

# A classifier maps (title, summary, tags) -> a category name, or None to leave Unsorted.
Classifier = Callable[[str, str, list[str]], str | None]


def classify_schema(categories: list[str]) -> dict:
    """Structured-output schema constraining `category` to the user's set + null (Unsorted).

    The enum is the hard gate that stops the model coining or picking anything off-list; null
    lets a genuinely off-topic article stay Unsorted rather than be force-fit.
    """
    return {
        "name": "classify",
        "schema": {
            "type": "object",
            "properties": {"category": {"enum": [*categories, None]}},
            "required": [],
        },
    }


_SYSTEM = (
    "You file one article into exactly one of the user's categories, chosen by what the article is "
    "ABOUT and its application -- not surface keywords. Return strict JSON matching the schema. "
    "Choose `category` ONLY from this exact list: [{listed}]. If none clearly fits, use null (the "
    "article stays Unsorted). Never invent or reword a category."
)


def build_classify_messages(
    title: str, summary: str, tags: list[str], categories: list[str]
) -> list[dict]:
    """Build the classification chat messages: the category contract plus the article's content.

    Args:
        title: Article title.
        summary: The card's stored LLM summary (re-used; not re-fetched).
        tags: The card's tags, for extra topical signal.
        categories: The user's managed category names (the allowed enum).

    Returns:
        A two-element [system, user] messages list for chat_json.
    """
    tag_line = ", ".join(tags) if tags else ""
    user = f"TITLE: {title}\n\nSUMMARY: {summary}\n\nTAGS: {tag_line}"
    return [
        {"role": "system", "content": _SYSTEM.format(listed=" | ".join(categories))},
        {"role": "user", "content": user},
    ]


def parse_category(raw: dict, allowed: set[str]) -> str | None:
    """Extract the chosen category, mapping anything outside the allowed set to None (Unsorted).

    The post-validation backstop for the enum: even a model that ignores the schema can never
    write a category the user has not defined.
    """
    category = raw.get("category") or None
    return category if category in allowed else None


def default_classifier(settings, categories: list[str]) -> Classifier:
    """Bind a classifier to the configured model + key (the real network path).

    Args:
        settings: App settings carrying enrich_model and openrouter_api_key.
        categories: The user's managed category names (the allowed enum).

    Returns:
        A callable mapping (title, summary, tags) to a chosen category or None (Unsorted).
    """
    schema = classify_schema(categories)
    allowed = set(categories)

    def classify(title: str, summary: str, tags: list[str]) -> str | None:
        raw = chat_json(
            build_classify_messages(title, summary, tags, categories),
            schema,
            model=settings.enrich_model,
            api_key=settings.openrouter_api_key or "",
        )
        return parse_category(raw, allowed)

    return classify
