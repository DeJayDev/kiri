import sqlite3

from kiri import db


def test_a_version_1_database_loses_the_dead_pinned_column(tmp_path):
    db.database.close()
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE sessions (channel_id INTEGER PRIMARY KEY, messages TEXT, summary TEXT, pinned TEXT, last_input_tokens INTEGER);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY, cron TEXT, instruction TEXT, channel_id INTEGER, next_run REAL, created REAL);
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


def test_a_version_2_database_gains_empty_session_notes(tmp_path):
    db.database.close()
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE sessions (channel_id INTEGER PRIMARY KEY, messages TEXT, summary TEXT, last_input_tokens INTEGER);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY, cron TEXT, instruction TEXT, channel_id INTEGER, next_run REAL, created REAL);
        CREATE TABLE usage (id INTEGER PRIMARY KEY, ts REAL, day TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_write_tokens INTEGER, cache_read_tokens INTEGER);
        INSERT INTO sessions VALUES (1, '[]', 'kept', 7);
        PRAGMA user_version = 2;
        """
    )
    raw.close()

    db.bind(path)

    assert db.Conversation.get_by_id(1).notes == "[]"


def test_a_version_3_database_keeps_its_jobs_and_can_hold_watches(tmp_path):
    db.database.close()
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE sessions (channel_id INTEGER PRIMARY KEY, messages TEXT, summary TEXT, last_input_tokens INTEGER, notes TEXT);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY, cron TEXT, instruction TEXT, channel_id INTEGER, next_run REAL, created REAL);
        CREATE TABLE usage (id INTEGER PRIMARY KEY, ts REAL, day TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_write_tokens INTEGER, cache_read_tokens INTEGER);
        INSERT INTO jobs VALUES (1, '0 9 * * *', 'brief', 5, 0, 0);
        PRAGMA user_version = 3;
        """
    )
    raw.close()

    db.bind(path)

    job = db.Job.get_by_id(1)
    assert (job.cron, job.condition, job.every, job.expires) == ("0 9 * * *", None, None, None)
