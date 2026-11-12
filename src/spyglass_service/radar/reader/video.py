"""YouTube videos: the transcript as readable paragraphs, with the embedded player alongside.

The transcript is taken from the text already stored for the item when there is one, otherwise
from the engine's transcript lane (the yt-transcribe command, then the caption API). The reader
document carries `alt_url`, the privacy-friendly embed address the frontend plays.
"""

import html as html_lib
import logging
import re
from collections.abc import Callable

from spyglass_service.radar.reader.sanitize import clean_html

logger = logging.getLogger(__name__)

_YT_ID = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|live/|embed/)|youtu\.be/)([\w-]{6,})"
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A paragraph closes after this many sentences, or once it passes this many words.
_SENTENCES_PER_PARAGRAPH = 4
_WORDS_PER_PARAGRAPH = 90
# Auto-captions carry no punctuation; without sentence ends, text is cut at this many words.
_UNPUNCTUATED_CHUNK_WORDS = 60
_TIMESTAMP = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+(.*)$")

Transcriber = Callable[[str], str | None]


def youtube_id(url: str) -> str | None:
    """The video id in a YouTube, youtu.be or embed URL, or None."""
    match = _YT_ID.search(url)
    return match.group(1) if match else None


def embed_url(video_id: str) -> str:
    """The cookie-free embed address used by the player."""
    return f"https://www.youtube-nocookie.com/embed/{video_id}"


def default_transcriber(video_id: str) -> str | None:
    """Transcript text from the engine's transcript lane; None when unavailable."""
    from spyglass_service import documents

    return documents._fetch_transcript(video_id)  # noqa: SLF001 -- the engine's public lane is private


def _split_sentences(text: str) -> list[str]:
    """Sentences of `text`; unpunctuated captions are cut into fixed-size word chunks."""
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    if len(sentences) >= 3 or len(text.split()) < 2 * _UNPUNCTUATED_CHUNK_WORDS:
        return sentences
    words = text.split()
    return [" ".join(words[i:i + _UNPUNCTUATED_CHUNK_WORDS])
            for i in range(0, len(words), _UNPUNCTUATED_CHUNK_WORDS)]


def paragraphs_from_transcript(text: str) -> list[str]:
    """Group transcript text into paragraphs of a few sentences.

    Lines that begin with a timestamp ("1:23 text") start a paragraph and keep the time as a
    `<time>` element. Returns HTML fragments (already escaped), one per paragraph.
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    stamped = [_TIMESTAMP.match(ln) for ln in lines]
    if lines and all(stamped):
        return [
            f'<p><time>{html_lib.escape(m.group(1))}</time> {html_lib.escape(m.group(2).strip())}</p>'
            for m in stamped if m
        ]
    flat = re.sub(r"\s+", " ", text or "").strip()
    paragraphs: list[str] = []
    current: list[str] = []
    words = 0
    for sentence in _split_sentences(flat):
        current.append(sentence)
        words += len(sentence.split())
        if len(current) >= _SENTENCES_PER_PARAGRAPH or words >= _WORDS_PER_PARAGRAPH:
            paragraphs.append(" ".join(current))
            current, words = [], 0
    if current:
        paragraphs.append(" ".join(current))
    return [f"<p>{html_lib.escape(p)}</p>" for p in paragraphs]


def build_video(video_id: str, *, url: str, title: str, origin: str, stored_text: str | None,
                transcriber: Transcriber | None = None) -> dict:
    """Build the reader fields for a YouTube video.

    `stored_text` is a transcript already kept for the item (preferred, because fetching one can
    take minutes). Without any transcript the document still opens, with a notice and the player.
    """
    text = (stored_text or "").strip()
    if not text:
        try:
            text = ((transcriber or default_transcriber)(video_id) or "").strip()
        except Exception:  # noqa: BLE001 -- transcript libraries raise many custom errors
            logger.exception("transcript fetch failed for video %s", video_id)
            text = ""
    if text:
        body = "".join(paragraphs_from_transcript(text))
    else:
        body = "<p>No transcript is available for this video. Use the player to watch it.</p>"
    cleaned = clean_html(body, url)
    return {
        "kind": "video", "html": cleaned, "title": title, "byline": origin, "site": "YouTube",
        "lead_image": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "word_count": len(text.split()), "source_url": url, "alt_url": embed_url(video_id),
    }
