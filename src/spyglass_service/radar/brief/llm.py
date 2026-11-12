"""The small-writing-job language model call shared by the brief, the watch and papers.

Callers inject a function `(messages, schema) -> dict` in tests; in production `make_llm`
binds the configured writer model and OpenRouter key. With no key configured it returns None,
and every caller then falls back to a deterministic result instead of failing.
"""

from collections.abc import Callable

from spyglass_service.radar.llm import available, chat_json_for

LlmFn = Callable[[list[dict], dict], dict]


def make_llm(settings, purpose: str = "other") -> LlmFn | None:
    """Bind the writer model of the configured provider, or return None when it is not usable.

    `purpose` names the job in the usage table (see `radar.usage.PURPOSES`).
    """
    if not available(settings)[0]:
        return None

    def call(messages: list[dict], schema: dict) -> dict:
        """Post one structured-output request to the writer model."""
        return chat_json_for(settings, "writer", messages, schema, purpose=purpose)

    return call


def json_schema(name: str, properties: dict, required: list[str]) -> dict:
    """A strict `json_schema` response-format dict for an object with the given properties."""
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }
