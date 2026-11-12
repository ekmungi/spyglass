"""Build the watch register from a broad topic: ask a model, then verify every name.

Language models invent plausible organisations, so no name is kept until a news search for it
returns at least one result that actually names it.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar.models import WatchEntity
from spyglass_service.radar.brief.llm import LlmFn, json_schema, make_llm
from spyglass_service.radar.watch._news_fallback import SearchFn, default_search
from spyglass_service.radar.watch.registry import (
    KINDS,
    DuplicateEntity,
    create_entity,
    entity_dict,
    norm_name,
)

logger = logging.getLogger(__name__)

# How far back the verification search looks: an organisation that matters has news this year.
VERIFY_DAYS = 120
# Seconds between verification searches.
VERIFY_PAUSE = 1.0

_ORG = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
        "category": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "why": {"type": "string"},
        "query": {"type": "string"},
    },
    "required": ["name", "kind", "category", "aliases", "why", "query"],
    "additionalProperties": False,
}
SCHEMA = json_schema(
    "watch_organisations",
    {"organisations": {"type": "array", "items": _ORG}},
    ["organisations"],
)

PROMPT = (
    "You help a reader keep track of the organisations that matter for a topic. List 8 to "
    "12 real organisations (companies, research labs, regulators, key publications) for the "
    "topic. Only name organisations you are sure exist. For each give: name; kind (company, lab, "
    "regulator, person or publication; AI labs and model developers such as OpenAI or Anthropic "
    "are lab, not company); category, the name of a GROUP: use at most four different "
    "category names in the whole list, so each group holds several organisations, and name a "
    "group for the area it covers (for example Imaging AI, Agent tooling, AI "
    "labs, Open-weights models, Regulators), never for the organisation's type or for one organisation; "
    "aliases (other names it goes by, may be empty); why (one line on why it "
    "matters); query (a precise news search string that finds news about it, such as the quoted "
    "name plus one disambiguating word)."
)


@dataclass
class DiscoverResult:
    """What a discovery run did: the entities stored, the names that failed verification."""

    accepted: list[dict] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)


def _names_it(texts: list[str], names: list[str]) -> bool:
    """True when any text contains any of the names as a whole phrase (ignoring case)."""
    haystacks = [f" {norm_name(t)} " for t in texts]
    return any(f" {norm_name(n)} " in h for n in names if norm_name(n) for h in haystacks)


# Corporate endings that headlines usually leave out ("Olympus Corporation" appears as "Olympus").
_SUFFIXES = frozenset(
    "corporation corp inc incorporated ltd limited llc plc gmbh ag sa co company group holdings "
    "systems medical healthcare technologies technology labs lab".split()
)


def core_name(raw: str) -> str:
    """The main name of an entry: text before any bracket or slash, without corporate endings."""
    words = re.split(r"\s+/\s+|\(", raw)[0].split()
    while len(words) > 1 and words[-1].lower().strip(".,") in _SUFFIXES:
        words.pop()
    return " ".join(words)


def name_forms(entity: dict) -> list[str]:
    """Ways a headline might name the entity: its names and aliases, parts, and without suffixes."""
    forms: list[str] = []
    for raw in [entity["name"], *entity.get("aliases", [])]:
        for part in re.split(r"\s+/\s+|\(|\)", raw):
            words = part.split()
            while len(words) > 1 and words[-1].lower().strip(".,") in _SUFFIXES:
                words.pop()
            for candidate in (part.strip(), " ".join(words)):
                if len(norm_name(candidate)) >= 3 and candidate not in forms:
                    forms.append(candidate)
    return forms


def make_verifier(search: SearchFn, sleep: Callable[[float], None] = time.sleep, pause: float = VERIFY_PAUSE):
    """A `verify(entity_dict) -> bool` that keeps an entity only if news results name it.

    It runs the entity's own query first; when no result names it, it tries the plain quoted
    name, because a model-written query can be narrower than the organisation's news coverage.
    """
    state = {"calls": 0}

    def run(query: str) -> list:
        """One throttled search; a failure counts as no results."""
        if state["calls"]:
            sleep(pause)
        state["calls"] += 1
        try:
            return search(query, days=VERIFY_DAYS)
        except Exception:
            logger.exception("Verification search failed for query %r", query)
            return []

    def verify(entity: dict) -> bool:
        """Check that a news result names the entity."""
        names = name_forms(entity)
        plain = f'"{core_name(entity["name"])}"' if names else None
        for query in dict.fromkeys(q for q in (entity.get("query"), plain) if q):
            if any(_names_it([r.title, r.summary or ""], names) for r in run(query)):
                return True
        return False

    return verify


def _known_forms(session: Session) -> set[str]:
    """Normalised name forms (see `name_forms`) of every entity already in the register."""
    forms: set[str] = set()
    for entity in session.exec(select(WatchEntity)).all():
        forms |= {norm_name(f) for f in name_forms(entity_dict(entity))}
    return forms


def _clean(raw: dict, topic: str) -> dict | None:
    """Validate one proposed organisation; None when it lacks a usable name."""
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    kind = raw.get("kind") if raw.get("kind") in KINDS else "company"
    return {
        "name": name,
        "kind": kind,
        "category": str(raw.get("category") or "").strip() or "Other",
        "aliases": [str(a).strip() for a in raw.get("aliases") or [] if str(a).strip()],
        "why": str(raw.get("why") or "").strip() or None,
        "query": str(raw.get("query") or "").strip() or f'"{name}"',
        "topic": topic,
    }


def discover_detailed(
    engine: Engine,
    settings,
    topic: str,
    *,
    llm: LlmFn | None = None,
    verify: Callable[[dict], bool] | None = None,
    activate: bool = False,
    search: SearchFn | None = None,
) -> DiscoverResult:
    """Propose, verify and store organisations for `topic`; reports what was kept and dropped.

    llm: `(messages, schema) -> dict`; defaults to the writer model. Raises RuntimeError when
        there is no model to ask.
    verify: `(entity_dict) -> bool`; defaults to a news search for the entity's query.
    activate: store the entities as "active" (followed) rather than "suggested".
    """
    llm = llm or make_llm(settings, "discovery")
    if llm is None:
        raise RuntimeError("No language model is configured (set an OpenRouter key)")
    verify = verify or make_verifier(search or default_search(decode_limit=0))
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Topic: {topic}"}]
    proposals = llm(messages, SCHEMA).get("organisations") or []
    result = DiscoverResult()
    with Session(engine) as session:
        taken = _known_forms(session)
        seen: set[str] = set()
        for raw in proposals:
            entity = _clean(raw, topic) if isinstance(raw, dict) else None
            if entity is None or norm_name(entity["name"]) in seen:
                continue
            seen.add(norm_name(entity["name"]))
            forms = {norm_name(f) for f in name_forms(entity)}
            if forms & taken:  # same organisation under another spelling, or one of its units
                result.existing.append(entity["name"])
                continue
            if not verify(entity):
                result.rejected.append(entity["name"])
                continue
            try:
                stored = create_entity(
                    session, entity["name"], kind=entity["kind"], category=entity["category"],
                    status="active" if activate else "suggested", added_via="discovered",
                    aliases=entity["aliases"], query=entity["query"], why=entity["why"], topic=topic,
                )
            except DuplicateEntity:
                result.existing.append(entity["name"])
                continue
            taken |= forms
            result.accepted.append(entity_dict(stored))
    return result


def discover(engine: Engine, settings, topic: str, **kwargs) -> list[dict]:
    """Like `discover_detailed` but returns only the stored entities (as dicts)."""
    return discover_detailed(engine, settings, topic, **kwargs).accepted
