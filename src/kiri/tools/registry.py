import time

from kiri import spans
from kiri.scheduling import tool as scheduler
from kiri.tools import ask, history, reload, send_file, shell, task, web


class Registry:
    def __init__(self):
        self._tools = {}

    def add(self, schema, runner):
        self._tools[schema["name"]] = (schema, runner)

    def schemas(self):
        return [schema for schema, _ in self._tools.values()]

    async def run(self, name, args):
        entry = self._tools.get(name)
        if not entry:
            return f"error: unknown tool {name}"
        _, runner = entry
        started = time.monotonic()
        ok = False
        try:
            output = await runner(args)
            # Tools report failure as an "error: ..." result, not an exception.
            ok = not str(output).startswith("error")
            return output
        finally:
            spans.record("tool", name, (time.monotonic() - started) * 1000, ok)


def build(store, channel_id, mcp_tools, transport, base_system):
    # Built per channel so scheduler tools deliver to the right DM. mcp_tools is
    # a shared list of (schema, runner) loaded once at startup.
    registry = Registry()
    registry.add(shell.SCHEMA, shell.run)
    registry.add(reload.SCHEMA, reload.run)
    registry.add(ask.SCHEMA, ask.build(transport, channel_id))
    registry.add(send_file.SCHEMA, send_file.build(transport, channel_id))
    registry.add(history.SCHEMA, history.build(channel_id))

    def fresh():
        return build(store, channel_id, mcp_tools, transport, base_system)

    registry.add(task.SCHEMA, task.build(channel_id, base_system, fresh))
    registry.add(web.SEARCH_SCHEMA, web.search)
    registry.add(web.FETCH_SCHEMA, web.fetch)
    for schema, runner in scheduler.build(store, channel_id):
        registry.add(schema, runner)
    for schema, runner in mcp_tools:
        registry.add(schema, runner)
    return registry
