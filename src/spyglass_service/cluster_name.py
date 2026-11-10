"""Cluster-naming LLM contract for the Recategorize pass.

One cheap structured-output call proposes a short category name for a discovered cluster
(the naming step runs Python-side, as part of the mechanical pass). Kept separate from
recategorize.py -- the orchestration -- the same way enrich_prompt is separate from enrich,
so the prompt/schema can be unit-tested without any DB or index.
"""

from collections.abc import Callable

from spyglass_service.openrouter import chat_json

# Structured-output schema: the model returns exactly one short category name.
CLUSTER_NAME_SCHEMA = {
    "name": "cluster_name",
    "schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}

_SYSTEM = (
    "You name a single topical category for a group of related article titles. Return strict "
    "JSON matching the schema: a short 1-4 word noun phrase in Title Case, no trailing "
    "punctuation, general enough to cover every title in the group."
)


def build_name_messages(titles: list[str]) -> list[dict]:
    """Build the naming chat messages: the system contract plus the cluster's titles.

    Args:
        titles: Representative article titles from one cluster.

    Returns:
        A two-element [system, user] messages list for chat_json.
    """
    listed = "\n".join(f"- {t}" for t in titles)
    user = f"Article titles in this group:\n{listed}\n\nPropose one short category name covering them."
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def parse_cluster_name(raw: dict) -> str:
    """Extract the proposed name from the model's JSON, trimmed; empty string if absent."""
    return str(raw.get("name", "") or "").strip()


def default_namer(settings) -> Callable[[list[str]], str]:
    """Bind a namer to the configured model + key (the real network path).

    Args:
        settings: App settings carrying enrich_model and openrouter_api_key.

    Returns:
        A callable mapping a cluster's titles to a proposed category name.
    """
    def namer(titles: list[str]) -> str:
        raw = chat_json(
            build_name_messages(titles),
            CLUSTER_NAME_SCHEMA,
            model=settings.enrich_model,
            api_key=settings.openrouter_api_key or "",
        )
        return parse_cluster_name(raw)

    return namer
