from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from kiri import credentials
from kiri.oauth import Loopback, open_browser


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


async def login(name, url):
    loopback = Loopback()
    redirect_uri = await loopback.start()

    async def redirect_handler(auth_url):
        print(f"opening browser:\n  {auth_url}")
        open_browser(auth_url)

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
