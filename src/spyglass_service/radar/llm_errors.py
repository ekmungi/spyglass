"""The one error type for "the model could not be used right now".

It lives in its own module so the Claude route, the OpenRouter route and the judging code can all
raise or catch it without importing each other. It is a RuntimeError, so callers that already
catch RuntimeError (watch discovery) or any Exception (the brief and the paper finder) keep working.
The message is short and written for the reader: it is shown in the app when a run stops.
"""


class LlmUnavailable(RuntimeError):
    """The model cannot be used: missing, not signed in, out of credit, rate limited or too slow."""
