import sqlite3

from kiri import db


def test_a_version_1_database_loses_the_dead_pinned_column(tmp_path):
    db.database.close()
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE sessions (channel_id INTEGER PRIMARY KEY, messages TEXT, summary TEXT, pinned TEXT, last_input_tokens INTEGER);
        CREATE TABLE usage (id INTEGER PRIMARY KEY, ts REAL, day TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_write_tokens INTEGER, cache_read_tokens INTEGER);
        INSERT INTO sessions VALUES (1, '[]', 'kept', '[]', 7);
        PRAGMA user_version = 1;
        """
    )
    raw.close()

    db.bind(path)

    columns = {c.name for c in db.database.get_columns("sessions")}
    assert "pinned" not in columns
    row = db.Conversation.get_by_id(1)
    assert (row.summary, row.last_input_tokens) == ("kept", 7)
