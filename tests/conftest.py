import pytest

from kiri import config, db


@pytest.fixture(autouse=True)
def bound_db(tmp_path):
    db.bind(str(tmp_path / "test.db"))
    yield
    db.database.close()


@pytest.fixture(autouse=True)
def kiri_home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KIRI_HOME", str(tmp_path))
    monkeypatch.setattr(config, "EVENTS_DIR", str(tmp_path / "events"))
    monkeypatch.setattr(config, "INBOX_DIR", str(tmp_path / "inbox"))
