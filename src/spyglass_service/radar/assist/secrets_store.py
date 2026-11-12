"""API keys in the operating system's keyring, one entry per engine id.

Keys that the reader types into the app are stored here and nowhere else: not in the database,
not in a settings file, never in a response or a log line. Keys set through the environment
(`OPENROUTER_API_KEY` and so on) are read by the settings object and take precedence.
"""

import logging

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger(__name__)

SERVICE = "spyglass"


class SecretStoreError(RuntimeError):
    """The keyring could not store or remove a key; the message is safe to show."""


def get_secret(engine_id: str) -> str | None:
    """The stored key for an engine, or None when absent or the keyring cannot be read."""
    try:
        return keyring.get_password(SERVICE, engine_id) or None
    except KeyringError as exc:
        logger.warning("The keyring could not be read for %s: %s", engine_id, type(exc).__name__)
        return None


def set_secret(engine_id: str, value: str) -> None:
    """Store a key for an engine; raises SecretStoreError when the keyring is unavailable."""
    try:
        keyring.set_password(SERVICE, engine_id, value)
    except KeyringError as exc:
        logger.warning("The keyring could not store a key for %s: %s", engine_id, type(exc).__name__)
        raise SecretStoreError("This computer's keyring is not available, so the key was not saved.") from exc


def delete_secret(engine_id: str) -> None:
    """Remove a stored key; a missing key is not an error."""
    try:
        keyring.delete_password(SERVICE, engine_id)
    except PasswordDeleteError:
        return
    except KeyringError as exc:
        raise SecretStoreError("This computer's keyring is not available.") from exc
