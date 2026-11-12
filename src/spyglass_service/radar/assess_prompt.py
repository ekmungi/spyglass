"""Prompts, schemas and parsing for the two assessment stages: triage and digest.

Triage judges up to 20 items per call from title, publication and the first lines of text.
Digest reads one item's text and writes what the reader sees: a plain headline, why it matters
to them, key points, organisations named and an event key. Both stages share one rubric so a
score means the same at either stage. The static rubric and the reader's profile come first in
the system message, so provider-side prompt caching can reuse that prefix across calls.
"""

import html
import json
import re
from dataclasses import dataclass

from spyglass_service.radar.models import KINDS

# How much of the feed's own text triage sees; titles carry most of the signal.
SNIPPET_CHARS = 300
# How much of the full text digest reads; enough for the substance, cheap enough per item.
TEXT_CHARS = 7000
# Headline length cap in words (the prompt asks for 12; a little slack before cutting).
HEADLINE_WORDS = 14

RUBRIC = """You are the relevance filter for one reader's daily research radar. The reader is \
described below: who they are, the sections of their brief, the topics they follow, what to \
avoid, and titles they recently liked and disliked. Judge every item for THIS reader, not for \
a general audience. The reader reads widely inside their sections and wants little outside \
them.

HOW TO SCORE: first decide which section the item fits. An item that clearly fits a section \
starts at 70; move it up for substance and consequence, down when it is routine or carries no \
information. An item that fits no section starts at 15. Then check the anchors. A clickbait \
title, a video or a social-media post is not by itself a reason to score low: judge the subject.

THE LINE THAT MATTERS: items scoring 50 or more are read in full and can reach the reader; items \
under 50 are dropped. Hiding an item the reader would have wanted is the worse mistake, so when \
an item fits a section and you are unsure, score it 50-60, not 40-49. Keep scores under 50 for \
items you are confident the reader would skip.

SCORE 0-100, with these anchors:
90-100  Must see today. A move by a company, lab or regulator in the reader's field (product \
launch, regulatory clearance or decision, acquisition, major model release); a peer-reviewed \
clinical study squarely on a topic.
75-89   Clearly worth reading. Squarely on a topic and substantive: a technique, tool, guide or \
video on building or working with AI agents and coding assistants (MCP, harnesses, skills, \
memory, agent workflows) the reader could use this week; a notable lab's research or \
technical report; a concrete industry use case with results; a substantive analysis of AI's \
economics, policy, effect on work or strategic direction.
60-74   Worth reading. Fits a section with some substance: an essay or opinion on where AI, \
work and organisations are heading; an enterprise AI adoption story; an open-source \
repository, self-hosted app or developer tool the reader could use in their own work (the \
reader builds software and keeps such tools, AI or not); clinical research, trial methods or \
outcomes in the clinical areas the reader's topics name, even without AI.
45-59   Borderline. On a section but thin or routine: a minor product update, a generic AI \
explainer or listicle, a paper close to a topic without signs of real-world weight.
20-44   Not for this reader, though technical: routine preprints on general machine-learning \
methods (benchmarks, training tricks, architectures, theory) with no direct link to a topic; \
chip, hardware and data-centre detail; funding, earnings or deal news outside the reader's \
field; a famous executive's hype ("X says the singularity is here"); generic management advice.
0-19    Off the radar: anything on the avoid list, and anything with no technology, AI or \
health content (games, puzzles, entertainment, sports, consumer gadgets and deals, lifestyle, \
personal finance, general business).

RULES
- Papers and preprints: one squarely on a topic the reader follows (for example a model for \
surgical video or for reading medical images) scores 50-70, and 75 or more only with real-world \
weight: published in a journal, a clinical or regulatory angle, a strong lab or company behind \
it, or clear community attention. A preprint on general machine-learning methods scores 20-44, \
and so does one that only mentions a topic word in passing. Academic preprints on LLM agents, \
reasoning, memory or benchmarks count as general methods unless a major lab is behind them.
- The examples show the reader's taste better than the topic list. An item that is the same \
kind of thing as a liked example (same subject, kind of tool or kind of source) scores 65 or \
more even when no topic names it; one like a disliked example scores under 30.
- An item that matches the avoid list scores under 20, whatever else it mentions.
- Judge the content, not the outlet: a general outlet can carry an important story and a \
specialist feed can carry noise.
- When the text is missing or thin, judge by the title: a title squarely on a section scores \
as such.
"""

KIND_GUIDE = (
    "kind: news (something happened), release (a product, model or version shipped), research "
    "(a lab or company research post or report), paper (a scientific paper or preprint), post "
    "(a blog post, essay or newsletter issue), video, regulatory (a regulator's decision, "
    "guidance or filing), tool (software, a repository or library), opinion (commentary)."
)

TRIAGE_TASK = """TASK
You see each item's id, title, publication, source and the first lines of its text. For every \
item return: id; reason (at most 12 words: which topic, section or example it matches, or why \
it does not); score; section (one of the section keys, or "" when none fits); kind. Return \
exactly one row per id."""

DIGEST_TASK = """TASK
You now read the item's text. Give the final judgement and write the reader's brief entry. If \
the text is an error, login, bot-check or redirect page, ignore it: write the entry from the \
title and publication alone, give at most 2 key points, and never mention that the page could \
not be read.
- key_points: 3 or 4 short factual bullets from the text, with numbers where the source gives \
them. No opinion, no repetition of the headline.
- entities: organisations named (companies, labs, universities, regulators), at most 8.
- headline: what happened, in plain words, at most 12 words. Lead with who did it. No \
clickbait, no question, no "X: Y" subtitle, no hype words.
- why: at most 2 sentences addressed to the reader as "you": what you can do with this, or what \
it changes for you, tied to your topics. Concrete; never generic ("this is relevant to AI").
- event_key: a lowercase slug naming the underlying event so two reports of the same event \
get the same key: 3 to 5 words, actor-action-object, e.g. "openai-gpt-6-release" or \
"fda-clears-olympus-polyp-ai". Name the company that acted, never the outlet reporting it; no \
dates, adjectives or extra detail. For an essay, guide or paper with no event, slug its author \
or publisher and main subject.
- section: one of the section keys, or "" when none fits.
- kind: as defined above.
- score: the final 0-100 score under the rubric, now that you have read the text."""


@dataclass(frozen=True)
class TriageResult:
    """One item's triage judgement."""

    item_id: int
    score: int
    section: str
    kind: str


@dataclass(frozen=True)
class DigestResult:
    """One item's digest: the final judgement plus the text the reader sees."""

    headline: str
    why: str
    key_points: tuple[str, ...]
    entities: tuple[str, ...]
    event_key: str
    score: int
    section: str
    kind: str


def _section_enum(keys: list[str]) -> list[str]:
    """Allowed section values: the profile's keys plus "" for no section."""
    return [*keys, ""]


def triage_schema(keys: list[str]) -> dict:
    """Structured-output schema for a triage batch: {"items": [{id, reason, score, ...}]}."""
    row = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "reason": {"type": "string"},
            "score": {"type": "integer"},
            "section": {"type": "string", "enum": _section_enum(keys)},
            "kind": {"type": "string", "enum": list(KINDS)},
        },
        "required": ["id", "reason", "score", "section", "kind"],
        "additionalProperties": False,
    }
    return {
        "name": "triage",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": row}},
            "required": ["items"],
            "additionalProperties": False,
        },
    }


def digest_schema(keys: list[str]) -> dict:
    """Structured-output schema for one item's digest."""
    strings = {"type": "array", "items": {"type": "string"}}
    props = {
        "key_points": strings,
        "entities": strings,
        "headline": {"type": "string"},
        "why": {"type": "string"},
        "event_key": {"type": "string"},
        "section": {"type": "string", "enum": _section_enum(keys)},
        "kind": {"type": "string", "enum": list(KINDS)},
        "score": {"type": "integer"},
    }
    return {
        "name": "digest",
        "strict": True,
        "schema": {"type": "object", "properties": props, "required": list(props),
                   "additionalProperties": False},
    }


_TAG = re.compile(r"<[^>]+>")
# arXiv feed summaries open with "arXiv:2607.01234v1 Announce Type: new Abstract:".
_ARXIV_PREFIX = re.compile(r"^arXiv:\S+\s+Announce Type:\s*\S+\s+Abstract:\s*", re.IGNORECASE)


def clean_snippet(text: str | None, limit: int = SNIPPET_CHARS) -> str:
    """Plain text from a feed summary: tags and entities removed, whitespace collapsed, cut."""
    plain = " ".join(html.unescape(_TAG.sub(" ", text or "")).split())
    plain = _ARXIV_PREFIX.sub("", plain)
    return plain if len(plain) <= limit else plain[:limit].rstrip() + "…"


# A tag cut off at the end of a truncated title, e.g. '<a href="https://example.org/pa'.
_OPEN_TAG = re.compile(r"<[^>]*$")


def plain_title(title: str | None) -> str:
    """A title without markup (some feeds put HTML in titles); the raw text if nothing is left."""
    raw = " ".join((title or "").split())
    plain = " ".join(html.unescape(_OPEN_TAG.sub(" ", _TAG.sub(" ", raw))).split())
    return plain or raw


def triage_row(item_id: int, title: str, origin: str | None, source: str,
               snippet: str | None) -> dict:
    """The per-item input triage sees."""
    return {"id": item_id, "title": plain_title(title),
            "publication": origin or "", "source": source, "text": clean_snippet(snippet)}


def _system(profile_block: str, task: str) -> str:
    """System message: static rubric, then the profile, then the stage's task (stable first)."""
    return f"{RUBRIC}\n{profile_block}\n\n{KIND_GUIDE}\n\n{task}"


def build_triage_messages(profile_block: str, rows: list[dict]) -> list[dict]:
    """Messages for one triage batch; the items go in the user message as one JSON object each."""
    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    user = f"Judge these {len(rows)} items. Return one row per id.\n{lines}"
    return [{"role": "system", "content": _system(profile_block, TRIAGE_TASK)},
            {"role": "user", "content": user}]


def build_digest_messages(profile_block: str, item: dict, text: str) -> list[dict]:
    """Messages for one digest; `item` carries title, publication, source and url."""
    body = text[:TEXT_CHARS]
    user = (f"TITLE: {item.get('title', '')}\nPUBLICATION: {item.get('publication', '')}\n"
            f"SOURCE: {item.get('source', '')}\nURL: {item.get('url', '')}\n\nTEXT:\n{body}")
    return [{"role": "system", "content": _system(profile_block, DIGEST_TASK)},
            {"role": "user", "content": user}]


def _score(value: object) -> int:
    """A 0-100 integer score; raises ValueError for anything that is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"score is not a number: {value!r}")
    return max(0, min(100, int(round(float(value)))))


def _choice(value: object, allowed: list[str] | tuple[str, ...], default: str) -> str:
    """`value` when it is one of `allowed`, otherwise `default`."""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def parse_triage(raw: object, expected_ids: list[int], keys: list[str]) -> tuple[dict, list[int]]:
    """Parse a triage reply into ({id: TriageResult}, [ids missing or malformed])."""
    rows = raw.get("items") if isinstance(raw, dict) else None
    results: dict[int, TriageResult] = {}
    for row in rows if isinstance(rows, list) else []:
        try:
            item_id = int(row["id"])
            score = _score(row["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if item_id in expected_ids and item_id not in results:
            results[item_id] = TriageResult(
                item_id=item_id, score=score,
                section=_choice(row.get("section"), keys, ""),
                kind=_choice(row.get("kind"), KINDS, "news"),
            )
    return results, [i for i in expected_ids if i not in results]


def slugify(text: str, limit: int = 80) -> str:
    """Lowercase ASCII slug of letters, digits and single dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:limit].rstrip("-")


def _strings(value: object, cap: int) -> tuple[str, ...]:
    """Up to `cap` distinct non-empty strings from a list value."""
    out: list[str] = []
    for entry in value if isinstance(value, list) else []:
        text = " ".join(str(entry).split())
        if text and text not in out:
            out.append(text)
    return tuple(out[:cap])


def _clean_headline(text: str) -> str:
    """A headline without a trailing full stop; an over-long one is cut to 12 words, and the
    cut never leaves a dangling comma or dash."""
    words = text.split()
    if len(words) > HEADLINE_WORDS:
        words = words[:12]
    return " ".join(words).rstrip(" .,;:-–—")


def parse_digest(raw: object, keys: list[str]) -> DigestResult:
    """Parse a digest reply; raises ValueError when the headline or score is unusable."""
    if not isinstance(raw, dict):
        raise ValueError("digest reply is not an object")
    headline = _clean_headline(str(raw.get("headline") or ""))
    if not headline:
        raise ValueError("digest reply has no headline")
    return DigestResult(
        headline=headline,
        why=" ".join(str(raw.get("why") or "").split()),
        key_points=_strings(raw.get("key_points"), 4),
        entities=_strings(raw.get("entities"), 10),
        event_key=slugify(str(raw.get("event_key") or "")) or slugify(headline),
        score=_score(raw.get("score")),
        section=_choice(raw.get("section"), keys, ""),
        kind=_choice(raw.get("kind"), KINDS, "news"),
    )


def tier_for(score: int, *, from_user: bool = False) -> str:
    """Tier from a final score; an item the reader sent in is never below "notable"."""
    if score >= 80:
        tier = "top"
    elif score >= 60:
        tier = "notable"
    elif score >= 45:
        tier = "skim"
    else:
        tier = "out"
    return "notable" if from_user and tier in ("skim", "out") else tier
