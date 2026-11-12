"""Checks that keep reader-supplied text inert on a command line.

The command-line engines build an argument list from a model name and a session id. Neither is
ever passed through a shell, but on Windows a `.cmd` or `.bat` shim (the usual form of an
npm-installed tool) is run by `cmd.exe`, which reads `&`, `|`, `<`, `>`, `^`, `%`, `!` and quotes
inside the arguments. So values are checked against a strict pattern, and a batch-file command
refuses any argument carrying those characters.
"""

import re
from pathlib import PurePath

# A model name starts with a letter or digit (so it can never look like an option) and uses only
# the characters real model ids use: letters, digits, . _ : / [ ] @ + -
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\[\]@+-]{0,119}")
# Session ids from both tools are UUID-like tokens: letters, digits, dashes, underscores.
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
# Engine ids: built-in names and "custom-<name>".
ENGINE_ID_RE = re.compile(r"[a-z0-9_-]{1,40}")

_BATCH_SUFFIXES = (".cmd", ".bat")
_CMD_METACHARACTERS = frozenset('&|<>^%!"`\r\n\x00')


def valid_model(model: str) -> bool:
    """True when `model` is a plain model name that is safe as a command-line argument."""
    return MODEL_RE.fullmatch(model) is not None


def valid_session(session: str) -> bool:
    """True when `session` has the shape of a session id the command-line tools produce."""
    return SESSION_RE.fullmatch(session) is not None


def is_batch_file(command: str) -> bool:
    """True when the program to run is a Windows batch file, which `cmd.exe` interprets."""
    return PurePath(command).suffix.lower() in _BATCH_SUFFIXES


def assert_cmd_safe(command: list[str]) -> None:
    """Refuse a command whose program is a batch file and whose arguments carry cmd metacharacters.

    A real executable receives its arguments without any shell, so nothing is refused for it.
    Raises ValueError, naming the argument position but never echoing its text.
    """
    if not command or not is_batch_file(command[0]):
        return
    for index, arg in enumerate(command[1:], start=1):
        if _CMD_METACHARACTERS.intersection(arg):
            raise ValueError(
                f"Argument {index} contains command-shell metacharacters and was refused.")
