"""Choose the watch suggestions from the counted names: shortlist, fold and select.

The steps `suggest.refresh_suggestions` runs on the counts of `mentions.count_mentions`, between
reading the register and writing it. They touch no database; the numbers (shortlist size,
suggestions per section, the item minimum) belong to the caller and are passed in. A model's
answers come in as `classes`: per normalised name, the `type`, `organisation`, `same_as` and
`group` that `suggest.classify` returns.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from spyglass_service.radar.watch.registry import norm_name

Classes = Mapping[str, Mapping[str, str]]


@dataclass
class Candidate:
    """An organisation that may be suggested: its shown name, its group and its item ids per section."""

    label: str
    group: str
    items: dict[str, set[int]] = field(default_factory=dict)


@dataclass(frozen=True)
class Choice:
    """One organisation selected for a section, with the number of items there that name it."""

    key: str
    label: str
    group: str
    section: str
    count: int


def shortlist(items: dict[str, dict[str, set[int]]], sections: list[str], excluded: set[str],
              size: int) -> list[str]:
    """Per section, the `size` names in the most items there that are not `excluded`; each name once."""
    keys: dict[str, None] = {}
    for section in sections:
        ranked = sorted((key for key, by in items.items() if section in by and key not in excluded),
                        key=lambda key, s=section: (-len(items[key][s]), key))
        keys.update(dict.fromkeys(ranked[:size]))
    return list(keys)


def owner(key: str, classes: Classes) -> tuple[str, str] | None:
    """The organisation a classified name counts for: (normalised name, name as the model wrote it).

    A product, team or lab counts for its parent, followed up to the top. A spelling of a register
    entry counts for none (the entry is already known), and so does a person, a publication, any
    other name, and a product without a parent. The written name is empty for the name itself.
    """
    label, seen = "", set()
    while key in classes and key not in seen:
        seen.add(key)
        answer = classes[key]
        if answer["same_as"] or answer["type"] not in ("organisation", "product"):
            return None
        parent = norm_name(answer["organisation"])
        if not parent or parent == key:
            return (key, label) if answer["type"] == "organisation" else None
        key, label = parent, answer["organisation"]
    return key, label


def candidates(names: list[str], classes: Classes, items: dict[str, dict[str, set[int]]],
               forms: dict[str, str], excluded: set[str]) -> dict[str, Candidate]:
    """The organisations the classified names stand for, products and labs folded into their parent.

    A parent's items per section are the union of its own and its children's, so an item that names
    two of them counts once. A name without an answer waits for a cycle with a model; an organisation
    in `excluded` (already in the register) is not a candidate.
    """
    found: dict[str, Candidate] = {}
    for key in names:
        target = owner(key, classes) if key in classes else None
        if target is None or target[0] in excluded:
            continue
        org, written = target
        candidate = found.setdefault(org, Candidate(forms.get(org) or written,
                                                    classes[org]["group"] if org in classes else ""))
        if org not in classes and not candidate.group:  # a parent never asked about takes a child's group
            candidate.group = classes[key]["group"]
        for name in {key, org}:
            for section, ids in items.get(name, {}).items():
                candidate.items.setdefault(section, set()).update(ids)
    return found


def choose(found: dict[str, Candidate], sections: list[str], *, per_section: int,
           min_items: int) -> list[Choice]:
    """Each candidate in the section where it has the most items (the earlier section on a tie), then
    per section the `per_section` most-named that reach `min_items`, in section order."""
    rows: dict[str, list[Choice]] = {section: [] for section in sections}
    for key, candidate in found.items():
        sizes = {section: len(candidate.items.get(section, ())) for section in sections}
        section = max(sections, key=sizes.__getitem__)
        if sizes[section] >= min_items:
            rows[section].append(Choice(key, candidate.label, candidate.group, section, sizes[section]))
    return [choice for section in sections
            for choice in sorted(rows[section], key=lambda c: (-c.count, c.label.lower()))[:per_section]]


def spellings(names: list[str], classes: Classes, forms: dict[str, str],
              followed: dict[str, int]) -> list[tuple[str, int]]:
    """(spelling, entry id) for each organisation among `names` that is another name of a followed entry.

    `followed` maps the normalised name of each watched or paused entry to its id. A spelling of a
    rejected entry is not listed: it is only dropped.
    """
    return [
        (forms[key], followed[norm_name(classes[key]["same_as"])])
        for key in names
        if key in classes and classes[key]["type"] == "organisation"
        and norm_name(classes[key]["same_as"]) in followed
    ]
