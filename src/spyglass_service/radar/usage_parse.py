"""Turn each provider's token figures into one shape: fresh input, cache written, cache read, output.

Providers disagree about what "input" means. Claude Code and the Anthropic API report the tokens
outside the cache as `input_tokens` and the cached ones separately. OpenAI-compatible APIs (OpenRouter,
OpenAI, Gemini) report the whole prompt as `prompt_tokens` and list the cached part inside
`prompt_tokens_details`. Here `input` always means the tokens that were neither read from nor written
to the cache, so that `input + cache_write + cache_read` is the size of the whole prompt on every
provider. A figure the provider does not report is None, never zero.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Tokens:
    """What one model call used. `cost_usd` is the figure the provider reported, if any."""

    input: int | None = None
    cache_write: int | None = None
    cache_read: int | None = None
    output: int | None = None
    cost_usd: float | None = None

    @property
    def context(self) -> int | None:
        """The size of the whole prompt (fresh + cache written + cache read), or None if unknown."""
        parts = [v for v in (self.input, self.cache_write, self.cache_read) if v is not None]
        return sum(parts) if parts else None

    @property
    def cached_share(self) -> float | None:
        """The fraction of the prompt that was read from the cache, or None if unknown."""
        context = self.context
        if not context or self.cache_read is None:
            return None
        return self.cache_read / context


def _count(value: object) -> int | None:
    """A non-negative integer from a JSON value, or None when it is missing or not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def _money(value: object) -> float | None:
    """A cost in US dollars from a JSON value, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, float(value))


def claude_tokens(result: dict) -> Tokens | None:
    """The figures in the final `result` object of `claude -p --output-format json|stream-json`.

    The `usage` block holds `input_tokens`, `cache_creation_input_tokens`,
    `cache_read_input_tokens` and `output_tokens`; the cost is `total_cost_usd`. Returns None when
    the result has no usable block.
    """
    block = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(block, dict) or not block:
        return None
    tokens = Tokens(input=_count(block.get("input_tokens")),
                    cache_write=_count(block.get("cache_creation_input_tokens")),
                    cache_read=_count(block.get("cache_read_input_tokens")),
                    output=_count(block.get("output_tokens")),
                    cost_usd=_money(result.get("total_cost_usd")))
    return tokens if any(v is not None for v in (tokens.input, tokens.output)) else None


def openai_tokens(block: object) -> Tokens | None:
    """The figures in an OpenAI-style `usage` object (OpenRouter, OpenAI, Gemini's compat layer).

    `prompt_tokens` is the whole prompt; `prompt_tokens_details.cached_tokens` is the part read from
    the cache and `cache_write_tokens` the part written, where the provider says so. OpenRouter adds
    `cost` when asked for usage accounting.
    """
    if not isinstance(block, dict) or not block:
        return None
    prompt = _count(block.get("prompt_tokens"))
    details = block.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    read = _count(details.get("cached_tokens"))
    write = _count(details.get("cache_write_tokens"))
    fresh = None if prompt is None else max(0, prompt - (read or 0) - (write or 0))
    output = _count(block.get("completion_tokens"))
    if fresh is None and output is None:
        return None
    return Tokens(input=fresh, cache_write=write, cache_read=read, output=output,
                  cost_usd=_money(block.get("cost")))


def anthropic_tokens(start: object, delta: object) -> Tokens | None:
    """The figures of a streamed Anthropic Messages answer.

    `start` is the `usage` of the `message_start` event (input and cache figures); `delta` is the
    `usage` of the last `message_delta` event, whose `output_tokens` is the final count.
    """
    first = start if isinstance(start, dict) else {}
    last = delta if isinstance(delta, dict) else {}
    if not first and not last:
        return None
    output = _count(last.get("output_tokens"))
    if output is None:
        output = _count(first.get("output_tokens"))
    return Tokens(input=_count(first.get("input_tokens")),
                  cache_write=_count(first.get("cache_creation_input_tokens")),
                  cache_read=_count(first.get("cache_read_input_tokens")), output=output)
