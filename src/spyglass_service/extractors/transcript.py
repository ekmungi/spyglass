"""YouTube transcript acquisition: the yt-transcribe CLI, with a caption-API fallback.

Moved out of documents.py. This is the "transcript lane" -- for a YouTube
URL, the full text IS the caption transcript (the watch page itself is a consent-walled
app shell), so this bypasses the generic acquire+extract path entirely.
"""

import json
import os
import subprocess
from collections.abc import Callable

# The resolved yt-transcribe command, set once at startup by app wiring (explicit setting or
# auto-discovery). None until set; falls back to the env var, then the bare name.
_YT_CMD: str | None = None


def set_yt_transcribe_cmd(cmd: str | None) -> None:
    """Set the resolved yt-transcribe CLI command (called at startup / on a settings change)."""
    global _YT_CMD
    _YT_CMD = cmd or None


def _yt_transcribe_cmd() -> str:
    """The yt-transcribe CLI command: the resolved path, else the env var, else the bare
    name (which relies on PATH; if it is not found, the youtube-transcript-api fallback runs)."""
    return _YT_CMD or os.environ.get("SPYGLASS_YT_TRANSCRIBE_CMD") or "yt-transcribe"


def _default_cli_runner(args: list[str]) -> subprocess.CompletedProcess:
    """Run a command capturing stdout, never raising on a non-zero exit (we parse its JSON)."""
    return subprocess.run(args, capture_output=True, text=True, timeout=600, check=False)


def _fetch_transcript_via_cli(
    url: str,
    *,
    command: str | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
) -> str | None:
    """Transcript text via ``yt-transcribe video <url> --no-save``; None if unavailable/failed.

    Reuses the user's yt-transcribe engine (captions + AssemblyAI) through its stable
    --json/--no-save tooling contract: one JSON line to stdout, ``text`` on success or ``error``
    on a known failure, writing no vault file. Returns None on any failure (binary missing,
    non-JSON, error payload, blank text) so the caller can fall back to the in-process caption API.
    """
    run = runner or _default_cli_runner
    try:
        proc = run([command or _yt_transcribe_cmd(), "video", url, "--no-save"])
    except (FileNotFoundError, OSError):
        return None  # CLI not installed / not on PATH
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except (ValueError, TypeError):
        return None
    text = payload.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else None


def _fetch_transcript_youtube_api(video_id: str) -> str | None:
    """Fallback caption transcript via youtube-transcript-api (lazy import). Flaky -- YouTube
    IP-blocks it -- so it runs only when the yt-transcribe CLI is unavailable."""
    from youtube_transcript_api import YouTubeTranscriptApi

    fetched = YouTubeTranscriptApi().fetch(video_id)
    text = " ".join(snippet.text for snippet in fetched).strip()
    return text or None


def _fetch_transcript(video_id: str) -> str | None:
    """A video's transcript text: the robust yt-transcribe CLI first, caption-API fallback.

    The CLI takes a URL, so a canonical watch URL is reconstructed from the video id (yt-dlp
    resolves it). If the CLI yields nothing (not installed, or no transcript), fall back to the
    in-process caption API; both failing yields None (the caller records status 'empty').
    """
    text = _fetch_transcript_via_cli(f"https://www.youtube.com/watch?v={video_id}")
    if text is not None:
        return text
    try:
        return _fetch_transcript_youtube_api(video_id)
    except Exception:  # noqa: BLE001 -- the fallback lib raises rich custom errors; treat as no-text
        return None
