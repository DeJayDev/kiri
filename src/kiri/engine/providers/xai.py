import asyncio
import time

from kiri import config, http
from kiri.auth import credentials
from kiri.engine.providers.base import AuthRequired, DeviceCode, ProviderError
from kiri.engine.providers.openai import OpenAI

_API = "https://api.x.ai/v1"
_DISCOVERY = "https://auth.x.ai/.well-known/openid-configuration"


class XAI(OpenAI):
    name = "xai"

    def __init__(self):
        # Refresh tokens rotate and are single-use: two concurrent refreshes means
        # one invalidates the other's and the owner is silently logged out.
        self._lock = asyncio.Lock()
        self._endpoints = None

    def base_url(self):
        return _API

    def key(self):
        return config.XAI_API_KEY

    def missing(self):
        if self.key() or credentials.get(self.name):
            return None
        if not config.XAI_CLIENT_ID:
            return "xai client_id or XAI_API_KEY"
        return None

    async def endpoints(self):
        if self._endpoints is None:
            resp = await http.request("GET", _DISCOVERY, timeout=30.0)
            if resp.status_code != 200:
                raise RuntimeError(f"xai: oauth discovery failed ({resp.status_code})")
            self._endpoints = resp.json()
        return self._endpoints

    async def _form(self, url, form, retry=True):
        headers = {"content-type": "application/x-www-form-urlencoded"}
        resp = await http.request(
            "POST", url, headers=headers, data=form, timeout=30.0, retry=retry
        )
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"error": "non_json_response", "raw": resp.text[:300]}

    async def begin_login(self):
        if not config.XAI_CLIENT_ID:
            raise RuntimeError("xai: no client_id configured (providers.xai.client_id)")

        points = await self.endpoints()
        status, data = await self._form(
            points["device_authorization_endpoint"],
            {
                "client_id": config.XAI_CLIENT_ID,
                # offline_access is mandatory: no refresh token without it. Grok's
                # conversations:*, workspaces:* and org:read are declined.
                "scope": "openid offline_access api:access",
            },
        )
        if status != 200:
            raise RuntimeError(f"xai: device code request failed ({status}): {data}")

        return DeviceCode(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri_complete") or data["verification_uri"],
            interval=float(data.get("interval", 5)),
            expires_at=time.time() + float(data.get("expires_in", 900)),
        )

    async def finish_login(self, device):
        points = await self.endpoints()
        interval = device.interval
        while time.time() < device.expires_at:
            status, data = await self._form(
                points["token_endpoint"],
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device.device_code,
                    "client_id": config.XAI_CLIENT_ID,
                },
            )
            if status == 200:
                return self._store(data)

            error = data.get("error")
            if error == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            if error == "slow_down":
                interval += 5
                await asyncio.sleep(interval)
                continue
            raise RuntimeError(f"xai: login failed ({error or status}): {data}")

        raise RuntimeError("xai: device code expired before it was authorized")

    def _store(self, token):
        record = {
            "access_token": token["access_token"],
            "expires_at": time.time() + float(token.get("expires_in", 3600)),
            "scopes": (token.get("scope") or "").split(),
        }
        # A rotated refresh token is only present on some responses; never
        # overwrite a good one with nothing.
        refresh = token.get("refresh_token") or (credentials.get(self.name) or {}).get(
            "refresh_token"
        )
        if refresh:
            record["refresh_token"] = refresh
        credentials.save(self.name, record)
        return record

    async def token(self):
        async with self._lock:
            record = credentials.get(self.name)
            if not record:
                raise AuthRequired(self, "xai: not logged in")

            remaining = credentials.expires_in(record)
            # Refresh a minute ahead of expiry so a 401 mid-turn stays exceptional.
            if remaining is not None and remaining <= 60:
                record = await self._refresh(record)
            return record["access_token"]

    async def _refresh(self, record):
        refresh = record.get("refresh_token")
        if not refresh:
            raise AuthRequired(self, "xai: access token expired and there is no refresh token")
        if not config.XAI_CLIENT_ID:
            # Without it the form would carry client_id=None and the 400 that came
            # back would say "log in again" -- which is impossible for the same reason.
            raise RuntimeError("xai: cannot refresh without providers.xai.client_id")

        points = await self.endpoints()
        # Never retried: the refresh token is single-use, so a second attempt spends
        # one the server may have already consumed.
        status, data = await self._form(
            points["token_endpoint"],
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": config.XAI_CLIENT_ID,
            },
            retry=False,
        )
        if status >= 500:
            # xAI is down, the credential is fine. Asking the owner to log in again
            # would be a lie, and would burn a good refresh token.
            raise RuntimeError(f"xai: token endpoint returned {status}, cannot refresh right now")
        if status != 200:
            raise AuthRequired(self, f"xai: token refresh rejected ({status}). log in again.")

        return self._store(data)

    async def headers(self):
        token = self.key() or await self.token()
        return {"authorization": f"Bearer {token}", "content-type": "application/json"}

    def output_tokens(self, usage):
        # xAI excludes reasoning tokens from completion_tokens; OpenAI includes them.
        details = usage.get("completion_tokens_details") or {}
        return usage.get("completion_tokens", 0) + details.get("reasoning_tokens", 0)

    def check_model(self, requested, data):
        # xAI serves an alias as a different model: ask for grok-4, get grok-4.3.
        served = data.get("model")
        if served and requested and served != requested:
            raise RuntimeError(
                f"xai: asked for '{requested}' but the reply came from '{served}'. "
                "set model.name to an exact id from xAI's model list, not an alias."
            )

    async def complete(self, system, messages, tools, model=None):
        try:
            return await super().complete(system, messages, tools, model=model)
        except ProviderError as exc:
            if exc.status == 403 and not self.key():
                raise RuntimeError(
                    "xai returned 403 on the OAuth surface. OAuth API access is "
                    "allowlisted separately from the subscription. set XAI_API_KEY to "
                    "use the api-key surface, or run `kiri auth status`."
                ) from exc
            raise
