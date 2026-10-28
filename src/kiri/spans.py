import time
from contextlib import asynccontextmanager

from kiri.db import Span


def record(kind, name, ms, ok=True, first_token_ms=None):
    Span.create(ts=time.time(), kind=kind, name=name, ms=ms, first_token_ms=first_token_ms, ok=ok)


@asynccontextmanager
async def timed(kind, name):
    started = time.monotonic()
    ok = False
    try:
        yield
        ok = True
    finally:
        record(kind, name, (time.monotonic() - started) * 1000, ok)


def _percentile(values, q):
    return values[min(len(values) - 1, int(q * len(values)))]


def summary(days=7):
    since = time.time() - days * 86400
    groups = {}
    for span in Span.select().where(Span.ts >= since).order_by(Span.id):
        groups.setdefault((span.kind, span.name), []).append(span)
        if span.first_token_ms is not None:
            groups.setdefault(("ttft", span.name), []).append(span)

    rows = []
    for (kind, name), spans in sorted(groups.items()):
        field = "first_token_ms" if kind == "ttft" else "ms"
        values = sorted(getattr(span, field) for span in spans)
        errors = sum(1 for span in spans if not span.ok)
        rows.append((kind, name, len(values), _percentile(values, 0.5), _percentile(values, 0.95), errors))
    return rows


def print_summary():
    rows = summary()
    if not rows:
        print("\nno latency recorded yet")
        return
    print("\nlatency, last 7 days (ms)")
    print(f"{'kind':<6}{'name':<40}{'count':>8}{'p50':>9}{'p95':>9}{'errors':>8}")
    for kind, name, count, p50, p95, errors in rows:
        print(f"{kind:<6}{name[:39]:<40}{count:>8,}{p50:>9,.0f}{p95:>9,.0f}{errors:>8}")
