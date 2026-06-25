import time

from kiri.db import Job
from kiri.scheduling.store import JobStore


def test_job_store_add_list_delete():
    store = JobStore()
    job_id = store.add("0 13 * * *", "send commute", 99)
    assert job_id == 1

    rows = store.list(99)
    assert len(rows) == 1
    assert rows[0]["instruction"] == "send commute"
    assert rows[0]["cron"] == "0 13 * * *"

    assert store.delete(job_id, 99) is True
    assert store.list(99) == []
    assert store.delete(999, 99) is False


def test_job_store_scopes_by_channel():
    store = JobStore()
    store.add("0 9 * * *", "mine", 1)
    store.add("0 9 * * *", "theirs", 2)
    assert [r["instruction"] for r in store.list(1)] == ["mine"]
    assert store.delete(1, 2) is False  # wrong channel can't delete


def test_future_job_not_due():
    store = JobStore()
    store.add("0 13 * * *", "later", 1)
    assert store.due(time.time()) == []


def test_one_shot_is_due_then_completes():
    store = JobStore()
    job_id = store.add_once(0, "ping", 5)  # next_run=0 -> already due
    rows = store.list(5)
    assert rows[0]["cron"] is None
    assert [r["id"] for r in store.due(time.time())] == [job_id]
    store.complete(job_id)
    assert store.list(5) == []


def test_due_and_reschedule_moves_next_run():
    store = JobStore()
    job_id = store.add("* * * * *", "tick", 1)
    # Force it due, then confirm reschedule pushes next_run into the future.
    Job.update(next_run=0).where(Job.id == job_id).execute()
    assert [r["id"] for r in store.due(time.time())] == [job_id]
    store.reschedule(job_id, "* * * * *")
    assert store.due(time.time()) == []
