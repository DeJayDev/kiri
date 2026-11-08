import json
import os
import re
from contextlib import AsyncExitStack

from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import ImageContent

from kiri.auth import credentials
from kiri.auth import mcp as mcp_auth
from kiri.engine.providers.base import viewable
from kiri.tools.shell import _cap

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
    texts, images = [], []
    for item in result.content:
        if isinstance(item, ImageContent):
            if not viewable(item.mime_type, len(item.data) * 3 // 4):
                texts.append(f"[a {item.mime_type} image was left out: not a type or size you can view]")
                continue
            source = {"type": "base64", "media_type": item.mime_type, "data": item.data}
            images.append({"type": "image", "source": source})
            continue
        text = getattr(item, "text", None)
        texts.append(text if text is not None else str(item))
    out = _cap("\n".join(texts))
    if result.is_error:
        out = f"error: {out}"
    if not images:
        return out
    return [{"type": "text", "text": out}, *images] if out else images


def _runner(client, tool_name):
    async def run(args):
        result = await client.call_tool(tool_name, args)
        return _flatten(result)

    return run


async def _server(name, spec, stack):
    if not spec.get("url"):
        return StdioServerParameters(
            command=spec["command"],
            args=spec.get("args", []),
            env={**os.environ, **spec.get("env", {})},
        )

    if spec.get("headers"):
        http_client = create_mcp_http_client(headers=spec["headers"])
    elif credentials.get(mcp_auth.key(name)):
        http_client = create_mcp_http_client(auth=mcp_auth.runtime_provider(name, spec["url"]))
    else:
        # A remote server with no stored token needs a browser, which boot can't do.
        # Fail it rather than hang the bot on a login it can't perform.
        raise RuntimeError(f"not authorized, run `kiri mcp {name}`")

    # Passed in, so the transport leaves closing it to us.
    await stack.enter_async_context(http_client)
    return streamable_http_client(spec["url"], http_client=http_client)


def _reason(exc):
    # anyio wraps a server's real error in an ExceptionGroup whose own message says nothing.
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_reason(inner) for inner in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"


async def load(config_path, stack):
    # Returns a shared list of (schema, runner), and (server, reason) for each server
    # that failed to start. Sessions stay open for the process lifetime via the
    # caller's AsyncExitStack.
    if not os.path.exists(config_path):
        return [], []

    with open(config_path) as f:
        servers = json.load(f).get("servers", {})

    tools = []
    failed = []
    taken = {}
    for name, spec in servers.items():
        # One server that can't start must not keep Kiri from booting: it is reported
        # to the owner instead, and its tools are absent until a reload.
        try:
            async with AsyncExitStack() as server:
                client = await server.enter_async_context(Client(await _server(name, spec, server)))
                listed = await client.list_tools()
                started = server.pop_all()
        except Exception as exc:
            failed.append((name, _reason(exc)))
            continue
        await stack.enter_async_context(started)

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
                "input_schema": tool.input_schema,
            }
            tools.append((schema, _runner(client, tool.name)))
    return tools, failed
