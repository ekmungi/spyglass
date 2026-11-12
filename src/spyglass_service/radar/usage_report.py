"""The usage report: totals per day, per purpose and per model, the cached share and the ten most
expensive conversations, read from the usage table.
"""

from datetime import timedelta

from sqlalchemy import Engine as DbEngine
from sqlalchemy import func
from sqlmodel import Session, select

from spyglass_service.radar.models import AssistThread, utcnow
from spyglass_service.radar.usage import UsageCall

# Conversations listed in the report.
TOP_CONVERSATIONS = 10
_FIGURES = ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens")


def _sums() -> list:
    """The SQL aggregates every grouping shares: call count, one sum per figure, cost, and the
    number of calls that reported no figures at all."""
    columns = [func.count(UsageCall.id)]
    columns += [func.coalesce(func.sum(getattr(UsageCall, name)), 0) for name in _FIGURES]
    columns += [func.sum(UsageCall.cost_usd)]
    columns += [func.sum(func.iif(UsageCall.input_tokens.is_(None)
                                  & UsageCall.output_tokens.is_(None), 1, 0))]
    return columns


def _shape(values: tuple) -> dict:
    """The figures dict for one grouping from the values of `_sums`."""
    calls, fresh, written, read, output, cost, unreported = values
    context = int(fresh) + int(written) + int(read)
    return {
        "calls": int(calls), "input_tokens": int(fresh), "cache_write_tokens": int(written),
        "cache_read_tokens": int(read), "output_tokens": int(output), "context_tokens": context,
        "cached_share": (int(read) / context) if context else None,
        "cost_usd": round(float(cost), 6) if cost is not None else None,
        "unreported_calls": int(unreported or 0),
    }


def _grouped(session: Session, since, *group) -> list[dict]:
    """Aggregate the rows since `since` by the given columns; the group values come first."""
    rows = session.exec(select(*group, *_sums()).where(UsageCall.at >= since).group_by(*group)
                        .order_by(*group)).all()
    width = len(group)
    return [{"keys": tuple(row[:width]), **_shape(tuple(row[width:]))} for row in rows]


def _conversations(session: Session, since) -> list[dict]:
    """The conversations that used the most in the window, most expensive first.

    Ranked by the cost the providers reported; a conversation with no reported cost ranks by its
    weighted tokens (cache reads count a tenth, cache writes a quarter more, output five times).
    """
    rows = _grouped(session, since, UsageCall.thread_id)
    rows = [r for r in rows if r["keys"][0] is not None]

    def weight(row: dict) -> tuple[float, float]:
        """Sort key: reported cost first, then weighted tokens."""
        tokens = (row["input_tokens"] + 1.25 * row["cache_write_tokens"]
                  + 0.1 * row["cache_read_tokens"] + 5 * row["output_tokens"])
        return (row["cost_usd"] or 0.0, tokens)

    top = sorted(rows, key=weight, reverse=True)[:TOP_CONVERSATIONS]
    threads = {t.id: t for t in session.exec(select(AssistThread).where(
        AssistThread.id.in_([r["keys"][0] for r in top]))).all()} if top else {}
    out = []
    for row in top:
        thread = threads.get(row["keys"][0])
        out.append({"thread_id": row["keys"][0], "title": thread.title if thread else "",
                    "item_id": thread.item_id if thread else None, "turns": row["calls"],
                    **{k: v for k, v in row.items() if k not in ("keys", "calls")}})
    return out


def build_report(engine: DbEngine, days: int = 7) -> dict:
    """The report for the last `days` days; raises ValueError for a window under one day.

    Keys: days, since, totals, per_day (oldest first, local days), by_purpose,
    by_model (purpose, provider and model) and conversations.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    since = utcnow() - timedelta(days=days)
    with Session(engine) as session:
        total = session.exec(select(*_sums()).where(UsageCall.at >= since)).one()
        day = func.date(UsageCall.at, "localtime")
        return {
            "days": days, "since": since.isoformat(),
            "totals": _shape(tuple(total)),
            "per_day": [{"day": r["keys"][0], **{k: v for k, v in r.items() if k != "keys"}}
                        for r in _grouped(session, since, day)],
            "by_purpose": [{"purpose": r["keys"][0], **{k: v for k, v in r.items() if k != "keys"}}
                           for r in _grouped(session, since, UsageCall.purpose)],
            "by_model": [{"purpose": r["keys"][0], "provider": r["keys"][1], "model": r["keys"][2],
                          **{k: v for k, v in r.items() if k != "keys"}}
                         for r in _grouped(session, since, UsageCall.purpose, UsageCall.provider,
                                           UsageCall.model)],
            "conversations": _conversations(session, since),
        }
