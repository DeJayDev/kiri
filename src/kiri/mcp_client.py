import json
import os
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _safe(name):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]


def _flatten(result):
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else str(item))
    out = "\n".join(parts)
    return f"error: {out}" if getattr(result, "isError", False) else out


def _runner(session, tool_name):
    async def run(args):
        result = await session.call_tool(tool_name, args)
        return _flatten(result)

    return run


async def load(config_path, stack):
    # Returns a shared list of (schema, runner). Sessions stay open for the
    # process lifetime via the caller's AsyncExitStack.
    if not os.path.exists(config_path):
        return []

    with open(config_path) as f:
        servers = json.load(f).get("servers", {})

    tools = []
    for name, spec in servers.items():
        params = StdioServerParameters(
            command=spec["command"],
            args=spec.get("args", []),
            env={**os.environ, **spec.get("env", {})},
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            schema = {
                "name": f"{_safe(name)}__{_safe(tool.name)}",
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            tools.append((schema, _runner(session, tool.name)))
    return tools
