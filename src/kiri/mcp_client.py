import json
import os
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from kiri.auth import credentials
from kiri.auth import mcp as mcp_auth

# Providers cap tool names at 64 chars, and one over-long name rejects the whole
# request. The tool half carries the meaning, so the prefix gets truncated hard.
_NAME_CAP = 64
_PREFIX_CAP = 20


def _safe(name):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _qualify(server, tool_name):
    prefix = _safe(server)[:_PREFIX_CAP]
    return f"{prefix}__{_safe(tool_name)}"[:_NAME_CAP]


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


async def _connect(name, spec, stack):
    if not spec.get("url"):
        params = StdioServerParameters(
            command=spec["command"],
            args=spec.get("args", []),
            env={**os.environ, **spec.get("env", {})},
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        return read, write

    # A remote server with no stored token needs a browser, which boot can't do.
    # Skip it and say so rather than hanging the bot on a login it can't perform.
    if not credentials.get(mcp_auth.key(name)):
        print(f"mcp: {name} is not authorized -- run `kiri mcp {name}`")
        return None

    auth = mcp_auth.runtime_provider(name, spec["url"])
    client = create_mcp_http_client(auth=auth)
    read, write, _ = await stack.enter_async_context(
        streamable_http_client(spec["url"], http_client=client)
    )
    return read, write


async def load(config_path, stack):
    # Returns a shared list of (schema, runner). Sessions stay open for the
    # process lifetime via the caller's AsyncExitStack.
    if not os.path.exists(config_path):
        return []

    with open(config_path) as f:
        servers = json.load(f).get("servers", {})

    tools = []
    taken = {}
    for name, spec in servers.items():
        streams = await _connect(name, spec, stack)
        if streams is None:
            continue

        read, write = streams
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            qualified = _qualify(name, tool.name)
            clash = taken.get(qualified)
            if clash:
                raise RuntimeError(
                    f"mcp tool name collision: {name}/{tool.name} and "
                    f"{clash[0]}/{clash[1]} both map to '{qualified}'. "
                    "rename one of the servers in mcp.json."
                )
            taken[qualified] = (name, tool.name)
            schema = {
                "name": qualified,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            tools.append((schema, _runner(session, tool.name)))
    return tools
