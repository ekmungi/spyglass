"""System prompt files for `claude -p`.

Claude Code puts its own cache breakpoints on the system prompt and on the last message only, and
the block that follows the first message carries a per-process scratch path, so anything sent as
the first message is rewritten to the cache on every call. The system prompt is the one place whose
text is read back from the cache by the next process. The instructions, the reader's profile and
(for the assistant) the article therefore go in a system prompt file, and only the part that
changes from call to call goes on standard input. A file also avoids the Windows command-line limit.

The file name is a hash of its text: the same text is always the same file, a changed profile is a
new one, and old ones are removed after a few days.
"""

import hashlib
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_PREFIX = "system-"


def _holds(path: Path, text: str) -> bool:
    """Whether `path` is a readable file with exactly `text` (a parallel writer got there first)."""
    try:
        return path.read_text(encoding="utf-8") == text
    except OSError:
        return False


def write_system_file(folder: Path, text: str) -> Path:
    """Write `text` to a file named after its hash in `folder` (once) and return the path.

    Parallel calls may write the same text at once. On Windows the final `replace` can then fail
    because another writer has the file open: that counts as success when the file already holds
    the text, and is tried once more otherwise. Raises OSError when the file cannot be had.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]
    path = folder / f"{_PREFIX}{digest}.txt"
    if path.is_file():
        try:
            path.touch()  # a file in use is not old
        except OSError:
            logger.warning("could not touch %s", path.name)
        return path
    folder.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(f".{uuid.uuid4().hex}.tmp")  # unique: calls run in parallel
    try:
        partial.write_text(text, encoding="utf-8", newline="\n")
        for attempt in (1, 2):
            try:
                partial.replace(path)  # atomic, so a parallel call never reads half a file
                return path
            except OSError:
                if _holds(path, text):
                    return path
                if attempt == 2:
                    raise
                time.sleep(0.05)
        return path  # not reached: the second failed attempt raises
    finally:
        partial.unlink(missing_ok=True)  # gone after a replace; left over only after a failure


def prune_system_files(folder: Path, max_age_days: float = 3.0) -> int:
    """Delete system prompt files not used for `max_age_days`; returns how many were removed.

    Never raises: a folder that cannot be listed or a file that cannot be removed is logged and
    skipped, because clearing old files is never a reason to fail a call.
    """
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        found = list(folder.glob(f"{_PREFIX}*.txt"))
    except OSError:
        logger.warning("could not list old system prompt files in %s", folder.name)
        return 0
    for path in found:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("could not remove %s", path.name)
    return removed
