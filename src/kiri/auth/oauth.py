import asyncio
import base64
import hashlib
import platform
import secrets
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlparse

from kiri import http
from kiri.auth import credentials

# Plugins that construct an OAuth register here, so `kiri auth` can find them
# without a separate manifest. Populated by importing kiri.tools.registry.
CLIENTS = {}


def key(name):
    return f"oauth:{name}"


class Loopback:
    # Authorization-code flows hand the code back through the browser, so it
    # needs somewhere to land. Port 0: the OS picks, nothing to configure.
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
            self.result.set_exception(RuntimeError(f"oauth: authorization denied ({error})"))

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


def open_browser(url):
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    try:
        subprocess.run([opener, url], check=False, capture_output=True)
    except FileNotFoundError:
        pass  # headless: the printed url is the fallback


def _challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class OAuth:
    # Authorization-code + PKCE against a service that issues a client_id up front
    # (Google, Notion, Spotify). mcp_auth covers the other half of the world:
    # servers that register a client dynamically per RFC 7591. Almost nothing
    # outside MCP does that, so a plugin talking to a real API wants this one.
    #
    # auth_params carries whatever the service demands to hand back a refresh
    # token at all -- Google wants access_type=offline and prompt=consent, and
    # silently issues an access-token-only grant without them.
    def __init__(
        self, name, client_id, client_secret, auth_url, token_url, scopes, auth_params=None
    ):
        self.name = name
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.token_url = token_url
        self.scopes = scopes
        self.auth_params = auth_params or {}
        # Refresh tokens may be single-use: two concurrent refreshes means one
        # invalidates the other's and the owner is silently logged out.
        self._lock = asyncio.Lock()
        CLIENTS[name] = self

    def missing(self):
        if not self.client_id:
            return f"{self.name} client_id"
        return None

    async def _form(self, form, retry=True):
        if self.client_secret:
            form = {**form, "client_secret": self.client_secret}
        headers = {"content-type": "application/x-www-form-urlencoded"}
        resp = await http.request(
            "POST", self.token_url, headers=headers, data=form, timeout=30.0, retry=retry
        )
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"error": "non_json_response", "raw": resp.text[:300]}

    async def login(self):
        if not self.client_id:
            raise RuntimeError(f"{self.name}: no client_id configured")

        loopback = Loopback()
        redirect_uri = await loopback.start()
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(16)

        url = f"{self.auth_url}?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.scopes),
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
                "state": state,
                **self.auth_params,
            }
        )
        print(f"opening browser:\n  {url}")
        open_browser(url)

        try:
            code, returned = await loopback.result
        finally:
            await loopback.close()

        # Without this an attacker's code could be swapped in and Kiri would store
        # a token to the attacker's account.
        if returned != state:
            raise RuntimeError(f"{self.name}: oauth state mismatch, login rejected")

        status, data = await self._form(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            }
        )
        if status != 200:
            raise RuntimeError(f"{self.name}: token exchange failed ({status}): {data}")
        return self._store(data)

    def _store(self, token):
        record = {
            "access_token": token["access_token"],
            "expires_at": time.time() + float(token.get("expires_in", 3600)),
            "scopes": (token.get("scope") or "").split(),
        }
        # Google returns a refresh token on first consent and never again; a
        # rotating issuer returns a new one each time. Never overwrite a good one
        # with nothing.
        refresh = token.get("refresh_token") or (credentials.get(key(self.name)) or {}).get(
            "refresh_token"
        )
        if refresh:
            record["refresh_token"] = refresh
        credentials.save(key(self.name), record)
        return record

    async def token(self):
        async with self._lock:
            record = credentials.get(key(self.name))
            if not record:
                raise RuntimeError(
                    f"{self.name}: not authorized. run `kiri auth login {self.name}`"
                )

            remaining = credentials.expires_in(record)
            # Refresh a minute ahead of expiry so a 401 mid-turn stays exceptional.
            if remaining is not None and remaining <= 60:
                record = await self._refresh(record)
            return record["access_token"]

    async def _refresh(self, record):
        refresh = record.get("refresh_token")
        if not refresh:
            raise RuntimeError(
                f"{self.name}: access token expired and there is no refresh token. "
                f"run `kiri auth login {self.name}`"
            )

        # Never retried: a rotating refresh token is single-use, so a second
        # attempt spends one the server may have already consumed.
        status, data = await self._form(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": self.client_id,
            },
            retry=False,
        )
        if status >= 500:
            # The service is down, the credential is fine. Telling the owner to log
            # in again would be a lie, and would burn a good refresh token.
            raise RuntimeError(
                f"{self.name}: token endpoint returned {status}, cannot refresh right now"
            )
        if status != 200:
            raise RuntimeError(
                f"{self.name}: token refresh rejected ({status}). "
                f"run `kiri auth login {self.name}`"
            )
        return self._store(data)

    async def headers(self):
        return {"authorization": f"Bearer {await self.token()}"}
