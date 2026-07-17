import asyncio
import base64
import hashlib
import time

import pytest

from kiri import config
from kiri.auth import credentials, oauth


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "c.json"))


def _client(monkeypatch, forms):
    client = oauth.OAuth(
        name="google",
        client_id="cid",
        client_secret="secret",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar"],
        auth_params={"access_type": "offline"},
    )
    calls = []

    async def fake_form(form, retry=True):
        calls.append(form | {"_retry": retry})
        return forms.pop(0)

    monkeypatch.setattr(client, "_form", fake_form)
    return client, calls


def test_a_refresh_is_never_retried(monkeypatch):
    credentials.save(
        oauth.key("google"),
        {"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 1},
    )
    client, calls = _client(monkeypatch, [(200, {"access_token": "new", "expires_in": 3600})])

    assert asyncio.run(client.token()) == "new"
    grant, = [c for c in calls if c["grant_type"] == "refresh_token"]
    assert grant["_retry"] is False


def test_refresh_token_survives_a_response_that_omits_it(monkeypatch):
    credentials.save(
        oauth.key("google"),
        {"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 1},
    )
    client, _ = _client(monkeypatch, [(200, {"access_token": "new", "expires_in": 3600})])

    asyncio.run(client.token())

    assert credentials.get(oauth.key("google"))["refresh_token"] == "r1"


def test_a_server_outage_does_not_tell_the_owner_to_log_in_again(monkeypatch):
    credentials.save(
        oauth.key("google"),
        {"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 1},
    )
    client, _ = _client(monkeypatch, [(503, {})])

    with pytest.raises(RuntimeError, match="cannot refresh right now"):
        asyncio.run(client.token())
    assert credentials.get(oauth.key("google"))["refresh_token"] == "r1"


def test_a_live_token_is_not_refreshed(monkeypatch):
    credentials.save(
        oauth.key("google"),
        {"access_token": "live", "refresh_token": "r1", "expires_at": time.time() + 3600},
    )
    client, calls = _client(monkeypatch, [])

    assert asyncio.run(client.token()) == "live"
    assert calls == []


def test_pkce_challenge_is_the_unpadded_s256_of_the_verifier():
    expected = base64.urlsafe_b64encode(hashlib.sha256(b"verifier").digest()).rstrip(b"=").decode()
    assert oauth._challenge("verifier") == expected
    assert "=" not in oauth._challenge("verifier")


def test_constructing_a_client_registers_it_for_kiri_auth(monkeypatch):
    _client(monkeypatch, [])
    assert oauth.CLIENTS["google"].client_id == "cid"


class _FakeLoopback:
    returned_state = "attacker"

    def __init__(self):
        self.result = asyncio.get_running_loop().create_future()
        self.result.set_result(("code", self.returned_state))

    async def start(self):
        return "http://127.0.0.1:1/callback"

    async def close(self):
        pass


def test_a_callback_with_the_wrong_state_is_rejected(monkeypatch):
    monkeypatch.setattr(oauth, "Loopback", _FakeLoopback)
    monkeypatch.setattr(oauth, "open_browser", lambda url: None)
    client, calls = _client(monkeypatch, [(200, {"access_token": "attacker-token"})])

    with pytest.raises(RuntimeError, match="state mismatch"):
        asyncio.run(client.login())
    assert calls == []
    assert credentials.get(oauth.key("google")) is None
