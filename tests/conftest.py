import pytest

from kiri import db


@pytest.fixture(autouse=True)
def bound_db(tmp_path):
    # Every test gets a fresh tmp-file database, bound globally like at runtime.
    db.bind(str(tmp_path / "test.db"))
    yield
    db.database.close()
