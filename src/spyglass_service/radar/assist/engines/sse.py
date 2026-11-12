"""A small Server-Sent Events reader shared by the HTTP engines.

It takes the lines of a streamed response (already split by the HTTP client, which handles
chunks that end mid-line) and yields one (event name, data) pair per event. Comment lines
(starting with ":", used as keep-alives) and blank events are skipped.
"""

from collections.abc import Iterable, Iterator


def iter_sse(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (event, data) for each complete event in `lines`.

    An event ends at a blank line. Several `data:` lines of one event are joined with newlines,
    as the SSE format says. The event name defaults to "message". A final event with no trailing
    blank line is still yielded, because some servers close the stream right after `[DONE]`.
    """
    event = "message"
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue  # keep-alive comment
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            data.append(value)
        elif field == "event":
            event = value or "message"
    if data:
        yield event, "\n".join(data)
