"""Turn openFDA device records into items, and decide which records belong to which company.

Three kinds of record, all from the public openFDA device service (no key):

- 510(k) data: a clearance (decision code starting "SE", for example SESE) is "FDA clears ...".
  A De Novo grant is in the same data under a DEN number with decision code DENG.
- PMA data: an approval (code APPR). Most supplements are manufacturing changes, so only an
  original approval and the supplements that bring something new (panel-track and 180-day
  reviews) become items.
- Recall data: one item per recall event, however many products it covers.

Every field is outside text, so it goes through `clean_line` (control and invisible characters
removed, one line, bounded) before it reaches a title or summary. Each item is a watch item of the
`watch` source, labelled "FDA" and tagged "regulator", identified by the record number and linked
to the record on FDA's own site.
"""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import quote

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.radar.text_clean import clean_line
from spyglass_service.radar.watch.registry import norm_name

SOURCE = "watch"
ORIGIN = "FDA"
REGULATOR_TAG = "regulator"
_BASE = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/"
TITLE_MAX = 300
SUMMARY_MAX = 900
FIELD_MAX = 160
# Legal endings that do not tell two firms apart ("Inc.", "GmbH"); removed from the end of a name.
_LEGAL_ENDINGS = frozenset({
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "gmbh", "ag", "sa", "plc", "bv", "nv", "kk", "pte", "lp", "llp", "sas", "srl", "spa", "oy",
    "ab", "as", "sarl", "pty"})
# Names this short must match the whole firm name: "GE" would otherwise start dozens of firms.
_MIN_PREFIX_CHARS = 4
# PMA supplement kinds that carry something new (the rest are manufacturing and labelling changes).
_NEW_SUPPLEMENTS = ("panel track", "normal 180 day")


def firm_key(name: str) -> str:
    """A firm name in matching form: lower case, no punctuation, no legal ending."""
    words = norm_name(name or "").split()
    while len(words) > 1 and words[-1] in _LEGAL_ENDINGS:
        words.pop()
    return " ".join(words)


def name_matches(names: Iterable[str], candidate: str) -> bool:
    """True when `candidate` is one of the firm `names`, or starts with it as whole words.

    "Olympus" matches "Olympus Medical Systems Corp." but not "Not Olympus Inc" or "Olympusx", and
    never matches by containing the name. A name of fewer than four characters must match the
    whole firm name.
    """
    wanted = firm_key(candidate)
    if not wanted:
        return False
    for name in names:
        key = firm_key(name)
        if not key:
            continue
        if wanted == key or (len(key) >= _MIN_PREFIX_CHARS and wanted.startswith(key + " ")):
            return True
    return False


def _text(record: dict, key: str, limit: int = FIELD_MAX) -> str:
    """One field of a record as clean single-line text ("" when missing)."""
    return clean_line(record.get(key), limit)


def _when(text: str | None) -> datetime | None:
    """A 'YYYY-MM-DD' decision date as midnight UTC, or None when it is not a date."""
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _day(moment: datetime) -> str:
    """The calendar day of a record date, as written in the summaries."""
    return moment.strftime("%Y-%m-%d")


def _summary(parts: list[tuple[str, str]]) -> str:
    """'Label: value.' sentences for the parts that have a value, cut to the summary size."""
    sentences = [f"{label}: {value.rstrip('.')}." for label, value in parts if value]
    return clean_line(" ".join(sentences), SUMMARY_MAX)


def _code_text(record: dict, name: str = "") -> str:
    """'CODE (product name)' for a record's product code and, when known, its name."""
    code = _text(record, "product_code", 12).rstrip("-")
    return f"{code} ({name})" if code and name else code


def _product_name(record: dict) -> str:
    """The product-code name openFDA adds to a record (its `openfda.device_name`)."""
    extra = record.get("openfda")
    return clean_line(extra.get("device_name"), FIELD_MAX) if isinstance(extra, dict) else ""


def _headline_device(device: str) -> str:
    """The first device of a ';'-separated list for a headline, with the count of the others."""
    names = [n.strip() for n in device.split(";") if n.strip()]
    if len(names) < 2:
        return device
    return f"{names[0][:100]} and {len(names) - 1} more"


def _item(external_id: str, title: str, url: str, summary: str, when: datetime) -> CollectedItem:
    """The item all three record kinds build: a regulator item of the watch source."""
    return CollectedItem(source=SOURCE, external_id=external_id,
                         title=clean_line(title, TITLE_MAX), url=url, summary=summary,
                         source_tags=[REGULATOR_TAG], published_at=when, origin=ORIGIN)


def item_510k(record: dict) -> CollectedItem | None:
    """The item for a 510(k) clearance or a De Novo grant; None for any other decision."""
    number, code = _text(record, "k_number", 20), _text(record, "decision_code", 8).upper()
    when = _when(record.get("decision_date"))
    denovo = code == "DENG"
    if not number or when is None or not (denovo or code.startswith("SE")):
        return None
    device = _text(record, "device_name") or "a device"
    applicant = _text(record, "applicant") or "an unnamed applicant"
    shown = _headline_device(device)
    if denovo:
        title = f"FDA grants De Novo for {shown} from {applicant} ({number})"
        url = f"{_BASE}cfpmn/denovo.cfm?id={quote(number)}"
        decision, kind = "De Novo request granted", "denovo"
    else:
        title = f"FDA clears {shown} from {applicant} (510(k) {number})"
        url = f"{_BASE}cfpmn/pmn.cfm?ID={quote(number)}"
        decision, kind = _text(record, "decision_description") or "Substantially equivalent", "510k"
    summary = _summary([
        ("Device", device), ("Applicant", applicant),
        ("Decision", f"{decision} ({code}) on {_day(when)}"),
        ("Product code", _code_text(record, _product_name(record))),
        ("Advisory committee", _text(record, "advisory_committee_description")),
        ("Review", _text(record, "clearance_type"))])
    return _item(f"fda:{kind}:{number}", title, url, summary, when)


def item_pma(record: dict) -> CollectedItem | None:
    """The item for a PMA approval (an original, or a supplement that brings something new)."""
    number, supplement = _text(record, "pma_number", 20), _text(record, "supplement_number", 12)
    when = _when(record.get("decision_date"))
    if not number or when is None or not _text(record, "decision_code", 8).upper().startswith("APP"):
        return None
    kind = _text(record, "supplement_type", 60).lower()
    if supplement and not any(kind.startswith(new) for new in _NEW_SUPPLEMENTS):
        return None
    device = _text(record, "trade_name") or _text(record, "generic_name") or "a device"
    applicant = _text(record, "applicant") or "an unnamed applicant"
    label = f"{number}/{supplement}" if supplement else number
    what = "PMA supplement" if supplement else "PMA"
    title = f"FDA approves {device} from {applicant} ({what} {label})"
    if supplement:
        title = f"FDA approves a PMA supplement for {device} from {applicant} ({label})"
    url = f"{_BASE}cfpma/pma.cfm?id={quote(number + supplement)}"
    summary = _summary([
        ("Device", device), ("Generic name", _text(record, "generic_name")),
        ("Applicant", applicant), ("Decision", f"Approved on {_day(when)}"),
        ("Product code", _code_text(record)),
        ("Advisory committee", _text(record, "advisory_committee_description")),
        ("Approval order", _text(record, "ao_statement", 300))])
    return _item(f"fda:pma:{label}", title, url, summary, when)


def _first_clause(text: str) -> str:
    """The start of a product description, up to the first ';' or ' - ' (kept short)."""
    return re.split(r";| - ", text, maxsplit=1)[0].strip()[:90]


def items_recall(records: Iterable[dict]) -> list[CollectedItem]:
    """One item per recall event: products of the same event are merged into its first record."""
    events: dict[str, list[dict]] = {}
    for record in records:
        event = _text(record, "res_event_number", 20)
        if event and _when(record.get("event_date_posted")) is not None:
            events.setdefault(event, []).append(record)
    items = []
    for event, group in events.items():
        first = group[0]
        when = _when(first.get("event_date_posted"))
        firm = _text(first, "recalling_firm") or "A manufacturer"
        product = _first_clause(_text(first, "product_description")) or "a device"
        more = f" and {len(group) - 1} more" if len(group) > 1 else ""
        title = f"{firm} recalls {product}{more} (FDA recall {event})"
        reason = _text(first, "reason_for_recall", 300)
        count = f"{len(group)} products" if len(group) > 1 else ""
        # The record id in the address (cfres_id) is not the recall event number; without it the
        # link goes to the recall database's search page rather than to some other record.
        record_id = _text(first, "cfres_id", 20)
        url = f"{_BASE}cfRES/res.cfm" + (f"?ID={quote(record_id)}" if record_id else "")
        summary = _summary([
            ("Recalling firm", firm), ("Product", _text(first, "product_description")),
            ("Reason", reason), ("Status", _text(first, "recall_status")),
            ("Posted", _day(when)), ("Product code", _code_text(first)),
            ("Affected", count)])
        items.append(_item(f"fda:recall:{event}", title, url, summary, when))
    return items
