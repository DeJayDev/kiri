import asyncio
import platform
import subprocess
from urllib.parse import parse_qs, urlparse

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from kiri import credentials


def key(name):
    return f"mcp:{name}"


class Storage(TokenStorage):
    # Remote MCP servers register dynamically (RFC 7591), so the client_id is
    # issued at first login and has to be kept alongside the tokens.
    def __init__(self, name):
        self.name = name

    def _record(self):
        return credentials.get(key(self.name)) or {}

    def _merge(self, field, value):
        record = self._record()
        record[field] = value
        credentials.save(key(self.name), record)

    async def get_tokens(self):
        raw = self._record().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens):
        self._merge("tokens", tokens.model_dump(mode="json", exclude_none=True))

    async def get_client_info(self):
        raw = self._record().get("client_info")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info):
        self._merge("client_info", client_info.model_dump(mode="json", exclude_none=True))


def _metadata(redirect_uri):
    return OAuthClientMetadata(
        client_name="kiri",
        redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


async def _refuse(url):
    raise RuntimeError(f"mcp: authorization needed, run `kiri mcp <name>` ({url})")


def runtime_provider(name, url):
    # A stored refresh token renews itself silently; a *new* authorization needs a
    # browser, and a turn must never block waiting for one.
    return OAuthClientProvider(
        server_url=url,
        client_metadata=_metadata("http://127.0.0.1/callback"),
        storage=Storage(name),
        redirect_handler=_refuse,
    )


class _Loopback:
    # MCP is authorization-code + PKCE, so unlike xAI's device flow the browser
    # needs somewhere to land.
    def __init__(self):
        self.result = asyncio.get_running_loop().create_future()
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/callback"

    async def _handle(self, reader, writer):
        line = (await reader.readline()).decode()
        target = line.split(" ")[1] if " " in line else "/"
        params = parse_qs(urlparse(target).query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        # Anything with neither is not the callback: a favicon fetch, a browser
        # preconnect probe, a port scan. Answer 404 and keep waiting -- resolving
        # the future here would fail a login the owner is about to complete.
        if not code and not error:
            await self._respond(writer, "404 Not Found", "kiri: not the oauth callback")
            return

        if error:
            await self._respond(writer, "400 Bad Request", f"kiri: authorization failed ({error})")
        else:
            await self._respond(writer, "200 OK", "kiri: authorized, close this tab.")

        if self.result.done():
            return
        if code:
            self.result.set_result((code, params.get("state", [None])[0]))
        else:
            self.result.set_exception(RuntimeError(f"mcp: authorization denied ({error})"))

    async def _respond(self, writer, status, body):
        writer.write(
            f"HTTP/1.1 {status}\r\ncontent-type: text/plain\r\n"
            f"content-length: {len(body)}\r\n\r\n{body}".encode()
        )
        await writer.drain()
        writer.close()

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


def _open_browser(url):
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    try:
        subprocess.run([opener, url], check=False, capture_output=True)
    except FileNotFoundError:
        pass  # headless: the printed url is the fallback


async def login(name, url):
    loopback = _Loopback()
    redirect_uri = await loopback.start()

    async def redirect_handler(auth_url):
        print(f"opening browser:\n  {auth_url}")
        _open_browser(auth_url)

    provider = OAuthClientProvider(
        server_url=url,
        client_metadata=_metadata(redirect_uri),
        storage=Storage(name),
        redirect_handler=redirect_handler,
        callback_handler=lambda: loopback.result,
    )

    try:
        # Any authenticated request drives the whole flow: discovery, dynamic
        # registration, the browser round-trip, then the token exchange.
        client = create_mcp_http_client(auth=provider)
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                return [tool.name for tool in listed.tools]
    finally:
        await loopback.close()
