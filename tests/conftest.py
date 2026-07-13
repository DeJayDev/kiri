import pytest

from kiri import db


@pytest.fixture(autouse=True)
def bound_db(tmp_path):
    db.bind(str(tmp_path / "test.db"))
    yield
    db.database.close()
