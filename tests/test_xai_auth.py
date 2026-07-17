import asyncio
import time

import pytest

from kiri import config
from kiri.auth import credentials
from kiri.engine.providers.base import AuthRequired
from kiri.engine.providers.xai import XAI


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(config, "XAI_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "XAI_API_KEY", None)


def _provider(monkeypatch, forms):
    provider = XAI()
    provider._endpoints = {
        "device_authorization_endpoint": "https://auth.x.ai/oauth2/device/code",
        "token_endpoint": "https://auth.x.ai/oauth2/token",
    }
    calls = []

    async def fake_form(url, form, retry=True):
        calls.append(form | {"_retry": retry})
        return forms.pop(0)

    monkeypatch.setattr(provider, "_form", fake_form)
    return provider, calls


def test_a_refresh_is_never_retried(monkeypatch):
    credentials.save(
        "xai", {"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 1}
    )
    provider, calls = _provider(monkeypatch, [(200, {"access_token": "new", "expires_in": 3600})])

    asyncio.run(provider.token())

    grant, = [c for c in calls if c["grant_type"] == "refresh_token"]
    assert grant["_retry"] is False


def test_no_credential_raises_auth_required(monkeypatch):
    provider, _ = _provider(monkeypatch, [])
    with pytest.raises(AuthRequired):
        asyncio.run(provider.token())


def test_valid_token_is_used_as_is(monkeypatch):
    credentials.save("xai", {"access_token": "good", "expires_at": time.time() + 9999})
    provider, calls = _provider(monkeypatch, [])
    assert asyncio.run(provider.token()) == "good"
    assert calls == []


def test_expiring_token_is_refreshed_early(monkeypatch):
    credentials.save(
        "xai", {"access_token": "old", "expires_at": time.time() + 5, "refresh_token": "r1"}
    )
    provider, calls = _provider(
        monkeypatch,
        [(200, {"access_token": "new", "expires_in": 21600, "refresh_token": "r2"})],
    )
    assert asyncio.run(provider.token()) == "new"
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "r1"
    assert credentials.get("xai")["refresh_token"] == "r2"


def test_refresh_keeps_the_old_refresh_token_if_none_is_returned(monkeypatch):
    credentials.save(
        "xai", {"access_token": "old", "expires_at": time.time() - 1, "refresh_token": "keep"}
    )
    provider, _ = _provider(monkeypatch, [(200, {"access_token": "new", "expires_in": 600})])
    asyncio.run(provider.token())
    assert credentials.get("xai")["refresh_token"] == "keep"


def test_a_down_token_endpoint_does_not_log_you_out(monkeypatch):
    credentials.save(
        "xai", {"access_token": "old", "expires_at": time.time() - 1, "refresh_token": "good"}
    )
    provider, _ = _provider(monkeypatch, [(503, {"error": "service_unavailable"})])
    with pytest.raises(RuntimeError, match="cannot refresh right now"):
        asyncio.run(provider.token())
    assert credentials.get("xai")["refresh_token"] == "good"


def test_rejected_refresh_asks_for_a_new_login(monkeypatch):
    credentials.save(
        "xai", {"access_token": "old", "expires_at": time.time() - 1, "refresh_token": "dead"}
    )
    provider, _ = _provider(monkeypatch, [(400, {"error": "invalid_grant"})])
    with pytest.raises(AuthRequired):
        asyncio.run(provider.token())


def test_expired_token_without_refresh_asks_for_a_new_login(monkeypatch):
    credentials.save("xai", {"access_token": "old", "expires_at": time.time() - 1})
    provider, _ = _provider(monkeypatch, [])
    with pytest.raises(AuthRequired):
        asyncio.run(provider.token())


def test_concurrent_refreshes_run_once(monkeypatch):
    credentials.save(
        "xai", {"access_token": "old", "expires_at": time.time() - 1, "refresh_token": "r1"}
    )
    provider, calls = _provider(
        monkeypatch,
        [(200, {"access_token": "new", "expires_in": 21600, "refresh_token": "r2"})],
    )

    async def race():
        return await asyncio.gather(*[provider.token() for _ in range(5)])

    tokens = asyncio.run(race())
    assert tokens == ["new"] * 5
    assert len(calls) == 1


def test_device_login_polls_until_authorized(monkeypatch):
    provider, calls = _provider(
        monkeypatch,
        [
            (200, {
                "device_code": "dev",
                "user_code": "ABCD-1234",
                "verification_uri": "https://accounts.x.ai/oauth2/device",
                "verification_uri_complete": "https://accounts.x.ai/oauth2/device?user_code=ABCD-1234",
                "interval": 0,
                "expires_in": 900,
            }),
            (400, {"error": "authorization_pending"}),
            (400, {"error": "slow_down"}),
            (200, {"access_token": "fresh", "refresh_token": "r", "expires_in": 21600, "scope": "openid api:access"}),
        ],
    )

    async def flow():
        device = await provider.begin_login()
        assert device.user_code == "ABCD-1234"
        assert "user_code=ABCD-1234" in device.verification_uri
        await provider.finish_login(device)

    async def instant(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    asyncio.run(flow())

    record = credentials.get("xai")
    assert record["access_token"] == "fresh"
    assert record["refresh_token"] == "r"
    assert record["scopes"] == ["openid", "api:access"]


def test_expired_device_code_fails_loud(monkeypatch):
    provider, _ = _provider(
        monkeypatch,
        [(200, {
            "device_code": "dev",
            "user_code": "X",
            "verification_uri": "https://x",
            "interval": 0,
            "expires_in": -1,
        })],
    )

    async def flow():
        device = await provider.begin_login()
        await provider.finish_login(device)

    with pytest.raises(RuntimeError, match="expired"):
        asyncio.run(flow())


def test_api_key_bypasses_oauth(monkeypatch):
    monkeypatch.setattr(config, "XAI_API_KEY", "xai-key")
    provider, _ = _provider(monkeypatch, [])
    headers = asyncio.run(provider.headers())
    assert headers["authorization"] == "Bearer xai-key"
