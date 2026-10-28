import asyncio

from kiri import spans
from kiri.engine import llm
from kiri.tools.registry import Registry


def test_summary_reports_percentiles_and_errors_per_operation():
    for ms in [100, 200, 300, 400, 1000]:
        spans.record("tool", "shell", ms)
    spans.record("tool", "shell", 50, ok=False)

    (row,) = spans.summary()
    kind, name, count, p50, p95, errors = row
    assert (kind, name, count, errors) == ("tool", "shell", 6, 1)
    assert (p50, p95) == (300, 1000)


def test_a_streamed_llm_call_records_time_to_first_text():
    class _Provider:
        name = "fake"

        async def complete(self, system, messages, tools, model=None, on_text=None):
            await asyncio.sleep(0.01)
            on_text("hi")
            return {"content": [], "usage": {}}

    llm.use(_Provider(), timer=spans.record)
    try:
        asyncio.run(llm.complete("sys", [], None, model="m", on_text=lambda d: None))
    finally:
        llm.use(None)

    rows = {(kind, name): count for kind, name, count, *_ in spans.summary()}
    assert rows == {("llm", "fake/m"): 1, ("ttft", "fake/m"): 1}


def test_a_failed_llm_call_is_recorded_as_an_error():
    class _Provider:
        name = "fake"

        async def complete(self, system, messages, tools, model=None, on_text=None):
            raise RuntimeError("down")

    llm.use(_Provider(), timer=spans.record)
    try:
        asyncio.run(llm.complete("sys", [], None, model="m"))
    except RuntimeError:
        pass
    finally:
        llm.use(None)

    ((_kind, _name, _count, _p50, _p95, errors),) = spans.summary()
    assert errors == 1


def test_a_tool_error_result_counts_as_an_error():
    registry = Registry()

    async def failing(args):
        return "error: nope"

    registry.add({"name": "web_fetch"}, failing)
    asyncio.run(registry.run("web_fetch", {}))

    ((kind, name, _count, _p50, _p95, errors),) = spans.summary()
    assert (kind, name, errors) == ("tool", "web_fetch", 1)
