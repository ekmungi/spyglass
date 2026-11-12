"""Review the watch register: propose pauses, removals, additions and tidier groups.

The reader's "improve the topic collection". The model has no tools and changes nothing: it
reads a compact picture of the register (`review_data`) and proposes, and the reader ticks what
to apply (`review_apply`). Every proposal is checked here before it is returned: ids must be in
the register, group names must be valid, and an added organisation must be new and pass the same
news-search existence check as discovery, because models invent plausible names. Names from the
web reach the model only inside the privacy fence. With no model, or when the model fails, a
plain rule-based review runs instead and says so (`mode` "basic").
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.radar.brief.llm import LlmFn, json_schema, make_llm
from spyglass_service.radar.llm_errors import LlmUnavailable
from spyglass_service.radar.models import WatchEntity
from spyglass_service.radar.privacy import fence
from spyglass_service.radar.watch._news_fallback import default_search
from spyglass_service.radar.watch.discover import make_verifier, name_forms
from spyglass_service.radar.watch.groups import GroupError, clean_category
from spyglass_service.radar.watch.registry import KINDS, OTHER, entity_dict, norm_name
from spyglass_service.radar.watch.review_data import build_picture

logger = logging.getLogger(__name__)

__all__ = ["MAX_PER_KIND", "QUIET_DAYS", "build_picture", "review"]

# At most this many proposals of each kind come back, so the reader can take them in at a glance.
MAX_PER_KIND = 8
# The basic review proposes a pause for a name with no news for this long (or since it was added).
QUIET_DAYS = 45
# An unregistered organisation is proposed by the basic review from this many relevant items.
BASIC_MIN_ITEMS = 3
SUMMARY_MAX = 400

_REASON = {"type": "string"}
_ID = {"type": "integer"}


def _item(**props: dict) -> dict:
    """A strict nested object schema: every property required, nothing else allowed."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SCHEMA = json_schema(
    "watch_review",
    {
        "pause": {"type": "array", "items": _item(id=_ID, reason=_REASON)},
        "remove": {"type": "array", "items": _item(id=_ID, reason=_REASON)},
        "add": {"type": "array", "items": _item(
            name={"type": "string"}, kind={"type": "string", "enum": list(KINDS)}, category={"type": "string"},
            why={"type": "string"}, query={"type": "string"})},
        "regroup": {"type": "array", "items": _item(id=_ID, to={"type": "string"}, reason=_REASON)},
        "merge_groups": {"type": "array", "items": _item(**{"from": {"type": "string"}, "to": {"type": "string"},
                                                            "reason": _REASON})},
        "summary": {"type": "string"},
    },
    ["pause", "remove", "add", "regroup", "merge_groups", "summary"],
)

PROMPT = (
    "You help a busy reader keep a watch list of organisations (companies, labs, regulators) "
    "relevant and short. Each organisation is searched in the news once a day. You are given the list "
    "as data: per name its id, group, how many items it brought in this week and this month, the days "
    "since its last hit, and how many of its items the reader opened or saved. You also get the "
    "reader's sections and topics, and organisations that keep appearing in relevant news without "
    "being on the list. You cannot change anything; you only propose, and the reader decides.\n"
    "Propose, with a short plain reason (one sentence, addressed to the reader) for each: pause (a "
    "name that has gone quiet or that the reader never engages with; paused names stay and can be "
    "resumed), remove (a name that no longer fits the reader's topics), add (an organisation that "
    "fits the topics and is missing, or one of the unregistered names that keeps appearing), regroup "
    "(one name that belongs in another group; use an existing group name where one fits), "
    "merge_groups (two groups that cover the same area). Refer to names only by the exact ids given. "
    "Propose an add only for an organisation you are sure exists, with a precise news search string "
    "as its query. Do not propose changes to names added in the last 14 days. At most 8 proposals "
    "of each kind; fewer is better, and an empty list is a good answer when nothing needs changing. "
    "Group names are short (at most 60 characters). The summary is one or two plain sentences on the "
    "state of the collection."
)


def _cap(rows: list[dict]) -> list[dict]:
    """The first MAX_PER_KIND proposals."""
    return rows[:MAX_PER_KIND]


def _text(value: object, limit: int = 300) -> str:
    """A model-written field as short single-line text."""
    return " ".join(str(value or "").split())[:limit]


def _clean_ids(raw: object, register: dict[int, dict], taken: set[int], *, active_only: bool = False) -> list[dict]:
    """Proposals naming a register id: valid, not yet proposed, and (for pause) not already muted."""
    out: list[dict] = []
    for row in raw if isinstance(raw, list) else []:
        entry = register.get(row.get("id")) if isinstance(row, dict) else None
        if entry is None or entry["id"] in taken or (active_only and entry["status"] != "active"):
            continue
        taken.add(entry["id"])
        out.append({"id": entry["id"], "name": entry["name"], "category": entry["category"],
                    "reason": _text(row.get("reason"))})
    return out


def _clean_regroups(raw: object, register: dict[int, dict], taken: set[int]) -> list[dict]:
    """Regroup proposals with a valid id and a valid, different destination group."""
    out: list[dict] = []
    for row in raw if isinstance(raw, list) else []:
        entry = register.get(row.get("id")) if isinstance(row, dict) else None
        if entry is None or entry["id"] in taken:
            continue
        try:
            destination = clean_category(row.get("to")) or OTHER
        except GroupError:
            continue
        if destination.casefold() == entry["category"].casefold():
            continue
        taken.add(entry["id"])
        out.append({"id": entry["id"], "name": entry["name"], "from": entry["category"], "to": destination,
                    "reason": _text(row.get("reason"))})
    return out


def _clean_merges(raw: object, register: dict[int, dict]) -> list[dict]:
    """Group merges where `from` is an existing group and `to` is a different valid name."""
    sizes: dict[str, int] = {}
    for entry in register.values():
        sizes[entry["category"]] = sizes.get(entry["category"], 0) + 1
    by_fold = {name.casefold(): name for name in sizes}
    out: list[dict] = []
    seen: set[str] = set()
    for row in raw if isinstance(raw, list) else []:
        source = by_fold.get(str(row.get("from") or "").strip().casefold()) if isinstance(row, dict) else None
        if source is None or source in seen:
            continue
        try:
            destination = clean_category(row.get("to")) or OTHER
        except GroupError:
            continue
        if destination.casefold() == source.casefold():
            continue
        seen.add(source)
        out.append({"from": source, "to": destination, "reason": _text(row.get("reason")), "count": sizes[source]})
    return out


def _clean_adds(raw: object, known: set[str], verify: Callable[[dict], bool]) -> list[dict]:
    """Added organisations that are new to the register and pass the news-search existence check."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in raw if isinstance(raw, list) else []:
        name = _text(row.get("name"), 120) if isinstance(row, dict) else ""
        if not name or norm_name(name) in seen:
            continue
        seen.add(norm_name(name))
        try:
            category = clean_category(row.get("category")) or OTHER
        except GroupError:
            category = OTHER
        candidate = {
            "name": name, "kind": row.get("kind") if row.get("kind") in KINDS else "company",
            "category": category, "why": _text(row.get("why")), "query": _text(row.get("query"), 200) or f'"{name}"',
            "aliases": [],
        }
        if {norm_name(f) for f in name_forms(candidate)} & known:
            continue
        if not verify(candidate):
            logger.info("Review dropped an unverifiable addition: %s", name)
            continue
        out.append({k: candidate[k] for k in ("name", "kind", "category", "why", "query")})
        if len(out) == MAX_PER_KIND:
            break
    return out


def _known_forms(session: Session) -> set[str]:
    """Normalised name forms of every entity in the register, whatever its status."""
    forms: set[str] = set()
    for entity in session.exec(select(WatchEntity)).all():
        forms |= {norm_name(f) for f in name_forms(entity_dict(entity))}
    return forms


def _ai_review(llm: LlmFn, picture: dict, known: set[str], verify: Callable[[dict], bool] | None, search) -> dict:
    """Ask the model, then keep only the proposals that hold up. May raise what `llm` raises."""
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": fence(json.dumps(picture, ensure_ascii=False, indent=1))},
    ]
    answer = llm(messages, SCHEMA)
    if not isinstance(answer, dict):
        raise ValueError("The model's answer was not a JSON object")
    register = {row["id"]: row for row in picture["register"]}
    taken: set[int] = set()
    remove = _clean_ids(answer.get("remove"), register, taken)
    pause = _clean_ids(answer.get("pause"), register, taken, active_only=True)
    regroup = _clean_regroups(answer.get("regroup"), register, taken)
    adds_raw = answer.get("add")
    verify = verify or (make_verifier(search or default_search(decode_limit=0)) if adds_raw else None)
    add = _clean_adds(adds_raw, known, verify) if verify else []
    result = {
        "pause": _cap(pause), "remove": _cap(remove), "add": add, "regroup": _cap(regroup),
        "merge_groups": _cap(_clean_merges(answer.get("merge_groups"), register)),
    }
    return {**result, "summary": _text(answer.get("summary"), SUMMARY_MAX) or _summary(result)}


def _plural(n: int, one: str, many: str) -> str:
    """"1 name" or "3 names"."""
    return f"{n} {one if n == 1 else many}"


def _summary(result: dict) -> str:
    """A plain sentence describing what a review found, or that nothing needs changing."""
    parts = []
    if result["pause"]:
        parts.append(f"{_plural(len(result['pause']), 'name has', 'names have')} gone quiet")
    if result["remove"]:
        parts.append(f"{_plural(len(result['remove']), 'name', 'names')} may no longer fit")
    if result["add"]:
        parts.append(f"{_plural(len(result['add']), 'organisation keeps', 'organisations keep')} appearing "
                     "without being on your list")
    if result["regroup"] or result["merge_groups"]:
        parts.append("some groups could be tidier")
    if not parts:
        return "Nothing stands out; your list looks current."
    text = "; ".join(parts)
    return f"{text[0].upper()}{text[1:]}."


def basic_review(picture: dict) -> dict:
    """The rule-based review: pause quiet names, add organisations named in many relevant items.

    A name is quiet when it has had no hit for `QUIET_DAYS` days, or none since it was added that
    long ago. Added organisations come straight from the reader's own relevant items, so they
    need no existence check. Nothing is proposed for removal or regrouping without a model.
    """
    pause = [
        {"id": r["id"], "name": r["name"], "category": r["category"],
         "reason": (f"No news found for {r['idle_days']} days." if r["ever_hit"]
                    else f"Nothing found since it was added {r['added_days_ago']} days ago.")}
        for r in picture["register"] if r["status"] == "active" and r["idle_days"] >= QUIET_DAYS
    ]
    add = [
        {"name": u["name"], "kind": "company", "category": "Discovered",
         "why": f"Named in {u['items']} relevant items in the last 30 days.", "query": f'"{u["name"]}"'}
        for u in picture["unregistered"] if u["items"] >= BASIC_MIN_ITEMS
    ]
    result = {"pause": _cap(pause), "remove": [], "add": _cap(add), "regroup": [], "merge_groups": []}
    quiet = _plural(len(result["pause"]), "name has", "names have")
    keeps = _plural(len(result["add"]), "organisation keeps", "organisations keep")
    if result["pause"] and result["add"]:
        summary = f"{quiet} had no news for {QUIET_DAYS} days or more, and {keeps} appearing in your Feed without being on the list."
    elif result["pause"]:
        summary = f"{quiet} had no news for {QUIET_DAYS} days or more."
    elif result["add"]:
        summary = f"{keeps} appearing in your Feed without being on the list."
    else:
        summary = "Nothing stands out; your list looks current."
    return {**result, "summary": summary}


def review(
    engine: Engine,
    settings,
    *,
    llm: LlmFn | None = None,
    verify: Callable[[dict], bool] | None = None,
    search=None,
    now: datetime | None = None,
) -> dict:
    """Review the register; returns the proposals plus `mode` ("ai" or "basic").

    llm: `(messages, schema) -> dict`; defaults to the configured writer model, and no model means
    the basic review. When the model cannot be reached or answers with unusable JSON the basic
    review is returned with a `note` saying why. verify: `(entity_dict) -> bool` for an added
    organisation; defaults to a news search. now: naive UTC, only for tests.
    """
    llm = llm or make_llm(settings, "watch_review")
    with Session(engine) as session:
        picture = build_picture(session, now=now)
        known = _known_forms(session)
    if llm is not None:
        try:
            return {"mode": "ai", **_ai_review(llm, picture, known, verify, search)}
        except (LlmUnavailable, ValueError) as exc:
            logger.warning("Watch review fell back to the basic review: %s", exc)
            return {"mode": "basic", "note": f"The AI review could not run ({exc}), so this is the basic review.",
                    **basic_review(picture)}
    return {"mode": "basic", "note": "No AI model is set up, so this is the basic review.", **basic_review(picture)}
