"""The per-install secret of the "Send to Spyglass" bookmark button.

Any website can send a form to this service, so a page handed over by the button is only taken
into the waiting room when it carries this secret. The secret is a random 128-bit value created on
first use and kept in one file in the data folder (readable by the owner only where the platform
allows). The settings page reads it through a same-origin route and builds the button around it;
"Make a new button" replaces it, which stops every older button from working.

The secret is compared in constant time and never logged.
"""

import hmac
import logging
import os
import re
import secrets
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

KEY_FILE = "import_button.key"
# 16 random bytes, written as 32 lower-case hex characters.
KEY_BYTES = 16
_KEY_SHAPE = re.compile(r"[0-9a-f]{32}")
_LOCK = threading.Lock()


def _path(data_dir: Path | str) -> Path:
    """The file holding the key."""
    return Path(data_dir) / KEY_FILE


def _write(path: Path, key: str) -> None:
    """Write the key to `path` atomically, readable by the owner only where the system allows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(key)
    os.replace(temporary, path)


def button_key(data_dir: Path | str) -> str:
    """The button's key; created (and saved) the first time, or when the saved one is damaged."""
    path = _path(data_dir)
    with _LOCK:
        try:
            saved = path.read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            saved = ""
        if _KEY_SHAPE.fullmatch(saved):
            return saved
        key = secrets.token_hex(KEY_BYTES)
        _write(path, key)
        logger.info("created the bookmark button's key")
        return key


def rotate_button_key(data_dir: Path | str) -> str:
    """Replace the key with a new one and return it; buttons made with the old key stop working."""
    key = secrets.token_hex(KEY_BYTES)
    with _LOCK:
        _write(_path(data_dir), key)
    logger.info("replaced the bookmark button's key")
    return key


def key_matches(data_dir: Path | str, supplied: object) -> bool:
    """Whether `supplied` is the button's key (False for anything missing, malformed or wrong)."""
    if not isinstance(supplied, str) or not _KEY_SHAPE.fullmatch(supplied):
        return False
    return hmac.compare_digest(supplied.encode("ascii"), button_key(data_dir).encode("ascii"))
