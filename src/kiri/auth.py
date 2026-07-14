import asyncio
import json
import os

from kiri import config, credentials, http, mcp_auth
from kiri.engine import providers
from kiri.login import login as do_login


def run(args):
    action = args[0] if args else "status"
    if action == "status":
        return status()
    if action == "login":
        if len(args) < 2:
            raise SystemExit("usage: kiri auth login <provider>")
        return login(args[1])
    raise SystemExit("usage: kiri auth [status | login <provider>]")


def mcp(args):
    servers = {name: spec for name, spec in _mcp_servers().items() if spec.get("url")}
    if not args:
        return _list_mcp(servers)

    name = args[0]
    if name not in servers:
        known = ", ".join(servers) or "none"
        raise SystemExit(f"no remote mcp server '{name}' in {config.MCP_CONFIG} (have: {known})")

    tools = asyncio.run(mcp_auth.login(name, servers[name]["url"]))
    print(f"authorized. {name} exposes {len(tools)} tools: {', '.join(tools[:8])}")


def _list_mcp(servers):
    if not servers:
        print(f"no remote mcp servers in {config.MCP_CONFIG}")
        print('add one:  {"servers": {"linear": {"url": "https://mcp.linear.app/mcp"}}}')
        return
    for name in sorted(servers):
        state = "authorized" if credentials.get(mcp_auth.key(name)) else "not authorized"
        print(f"  {name:<12}{state}")
    print("\n`kiri mcp <server>` to authorize")


def _mcp_servers():
    if not os.path.exists(config.MCP_CONFIG):
        return {}
    with open(config.MCP_CONFIG) as f:
        return json.load(f).get("servers", {})


def status():
    active = {config.PROVIDER, config.SUMMARY_PROVIDER} - {None}
    for name, cls in providers.PROVIDERS.items():
        provider = cls()
        marker = "*" if name in active else " "
        gap = provider.missing()

        if credentials.get(name):
            state = credentials.describe(name)
        elif gap:
            state = f"not configured ({gap})"
        else:
            state = "api key set"

        print(f"{marker} {name:<12}{state}")


def login(name):
    provider = providers.build(name)
    if not hasattr(provider, "begin_login"):
        raise SystemExit(f"{name} uses an api key, not a login. set it in kiri.toml or the env.")
    asyncio.run(_login(provider))


async def _login(provider):
    async def say(text):
        print(text)

    try:
        await do_login(provider, say)
        print(f"token saved to {config.CREDENTIALS_PATH}")
    finally:
        await http.aclose()

