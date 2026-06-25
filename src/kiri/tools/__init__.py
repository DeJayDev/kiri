from ..scheduling import tool as scheduler
from . import shell, web


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
        return await runner(args)


def build(store, channel_id, mcp_tools):
    # Built per channel so scheduler tools deliver to the right DM. mcp_tools is
    # a shared list of (schema, runner) loaded once at startup.
    registry = Registry()
    registry.add(shell.SCHEMA, shell.run)
    registry.add(web.SEARCH_SCHEMA, web.search)
    registry.add(web.FETCH_SCHEMA, web.fetch)
    for schema, runner in scheduler.build(store, channel_id):
        registry.add(schema, runner)
    for schema, runner in mcp_tools:
        registry.add(schema, runner)
    return registry
