import asyncio
import json
from contextlib import AsyncExitStack

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from kiri import config, mcp_client
from kiri.auth import credentials
from kiri.auth import mcp as mcp_auth


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "c.json"))


def test_storage_roundtrips_tokens_and_dynamic_client_registration():
    storage = mcp_auth.Storage("linear")
    assert asyncio.run(storage.get_tokens()) is None
    assert asyncio.run(storage.get_client_info()) is None

    asyncio.run(storage.set_tokens(OAuthToken(access_token="a", refresh_token="r")))
    asyncio.run(
        storage.set_client_info(
            OAuthClientInformationFull(
                client_id="cid",
                redirect_uris=["http://127.0.0.1:1/callback"],
            )
        )
    )

    assert asyncio.run(storage.get_tokens()).refresh_token == "r"
    assert asyncio.run(storage.get_client_info()).client_id == "cid"
    assert set(credentials.get("mcp:linear")) == {"tokens", "client_info"}


def test_an_unauthorized_remote_server_is_skipped_not_fatal(monkeypatch, tmp_path, capsys):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": {"linear": {"url": "https://mcp.linear.app/mcp"}}}))

    async def go():
        async with AsyncExitStack() as stack:
            return await mcp_client.load(str(path), stack)

    assert asyncio.run(go()) == []
    assert "kiri mcp linear" in capsys.readouterr().out
