import os
import stat

import pytest

from kiri import config
from kiri.auth import credentials


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "credentials.json"))


def test_token_file_is_not_world_readable():
    credentials.save("xai", {"access_token": "a"})
    mode = stat.S_IMODE(os.stat(config.CREDENTIALS_PATH).st_mode)
    assert mode == 0o600


def test_save_does_not_clobber_other_providers():
    credentials.save("xai", {"access_token": "x"})
    credentials.save("anthropic", {"access_token": "a"})
    assert credentials.get("xai")["access_token"] == "x"
