"""The environment for the `claude -p` processes that answer questions and judge items.

Claude Code loads the owner's memory notes and instruction files into every request unless told
not to, even with `--setting-sources ""`. For these calls that is unwanted: it adds thousands of
tokens that have nothing to do with the question (measured: about 3,900 of 4,850 tokens of an
otherwise empty request when the data folder sits inside a git repository), and it sends the
owner's private notes to the model. The two switches below turn that off. `ANTHROPIC_API_KEY` is
dropped, so the calls bill the owner's plan.
"""

from spyglass_service.claude_jobs import child_env

# Documented Claude Code environment variables: no auto-memory, no CLAUDE.md files of any kind.
_QUIET = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}


def quiet_env() -> dict[str, str]:
    """The child environment for a judging or answering call: no memory, no instruction files."""
    return {**child_env(), **_QUIET}
