import time
from datetime import datetime, timezone

import peewee

from kiri.db import UsageEvent

# Token accounting, harness-internal. Persisted to the store so a separate
# `kiri usage` process can read it. The agent never touches this.


def record(usage):
    if not usage:
        return
    now = time.time()
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    UsageEvent.create(
        ts=now,
        day=day,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
    )


def _sum(field):
    # COALESCE because rows written before the cache columns existed are null.
    return peewee.fn.COALESCE(peewee.fn.SUM(field), 0)


def tally():
    rows = (
        UsageEvent.select(
            UsageEvent.day,
            _sum(UsageEvent.input_tokens),
            _sum(UsageEvent.cache_write_tokens),
            _sum(UsageEvent.cache_read_tokens),
            _sum(UsageEvent.output_tokens),
            peewee.fn.COUNT(UsageEvent.id),
        )
        .group_by(UsageEvent.day)
        .order_by(UsageEvent.day)
        .tuples()
    )
    return list(rows)


_WIDTHS = (12, 12, 12, 12, 12, 8)


def _row(day, *cells):
    widths = iter(_WIDTHS)
    out = f"{day:<{next(widths)}}"
    return out + "".join(f"{cell:>{w}}" for cell, w in zip(cells, widths))


def _numbers(row):
    return _row(row[0], *(f"{n:,}" for n in row[1:]))


def print_tally():
    rows = tally()
    if not rows:
        print("no usage recorded yet")
        return

    print(_row("day", "input", "cache w", "cache r", "output", "calls"))
    totals = [0, 0, 0, 0, 0]
    for row in rows:
        print(_numbers(row))
        for i, value in enumerate(row[1:]):
            totals[i] += value
    print(_numbers(("total", *totals)))

    cached = totals[2]
    prompt_tokens = totals[0] + totals[1] + cached
    if prompt_tokens:
        print(f"\ncache hit rate: {cached / prompt_tokens:.0%} of prompt tokens served from cache")
