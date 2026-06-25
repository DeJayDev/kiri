import time

from kiri.scheduling.store import JobStore


def test_job_store_add_list_delete(tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    job_id = store.add("0 13 * * *", "send commute", 99)
    assert job_id == 1

    rows = store.list(99)
    assert len(rows) == 1
    assert rows[0]["instruction"] == "send commute"
    assert rows[0]["cron"] == "0 13 * * *"

    assert store.delete(job_id, 99) is True
    assert store.list(99) == []
    assert store.delete(999, 99) is False


def test_job_store_scopes_by_channel(tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.add("0 9 * * *", "mine", 1)
    store.add("0 9 * * *", "theirs", 2)
    assert [r["instruction"] for r in store.list(1)] == ["mine"]
    assert store.delete(1, 2) is False  # wrong channel can't delete


def test_future_job_not_due(tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.add("0 13 * * *", "later", 1)
    assert store.due(time.time()) == []


def test_due_and_reschedule_moves_next_run(tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    job_id = store.add("* * * * *", "tick", 1)
    # Force it due, then confirm reschedule pushes next_run into the future.
    store.db.execute("UPDATE jobs SET next_run=? WHERE id=?", (0, job_id))
    store.db.commit()
    assert [r["id"] for r in store.due(time.time())] == [job_id]
    store.reschedule(job_id, "* * * * *")
    assert store.due(time.time()) == []
