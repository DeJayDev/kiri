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
    )


def tally():
    rows = (
        UsageEvent.select(
            UsageEvent.day,
            peewee.fn.SUM(UsageEvent.input_tokens),
            peewee.fn.SUM(UsageEvent.output_tokens),
            peewee.fn.COUNT(UsageEvent.id),
        )
        .group_by(UsageEvent.day)
        .order_by(UsageEvent.day)
        .tuples()
    )
    return list(rows)


def print_tally():
    rows = tally()
    if not rows:
        print("no usage recorded yet")
        return
    print(f"{'day':<12}{'input':>14}{'output':>14}{'calls':>9}")
    total_in = total_out = total_calls = 0
    for day, input_tokens, output_tokens, calls in rows:
        print(f"{day:<12}{input_tokens:>14,}{output_tokens:>14,}{calls:>9,}")
        total_in += input_tokens
        total_out += output_tokens
        total_calls += calls
    print(f"{'total':<12}{total_in:>14,}{total_out:>14,}{total_calls:>9,}")
