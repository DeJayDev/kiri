import asyncio
import time

from kiri import app, db
from kiri.engine.context import Session
from kiri.scheduling import store as scheduling
from kiri.scheduling import tool as scheduler
from kiri.scheduling.store import JobStore


class _Transport:
    name = "fake"

    def __init__(self):
        self.sent = []

    async def send(self, channel_id, text):
        self.sent.append(text)


class _Dispatcher:
    def __init__(self):
        self.transport = _Transport()
        self.session = Session(5, "base")
        self.sessions = self

    def get(self, channel_id):
        return self.session

    def note(self, channel_id, text):
        self.session.note(text)

    def archive(self, channel_id, messages):
        pass


def _tool(store, name):
    return dict((schema["name"], runner) for schema, runner in scheduler.build(store, 5))[name]


def _watch(store, condition, expires=None):
    job_id = store.add_watch(condition, "tell the owner the bridge is clear", 5, 300, expires or time.time() + 3600)
    return db.Job.select().where(db.Job.id == job_id).dicts().get()


def test_setting_a_watch_runs_the_condition_once_and_shows_its_output():
    store = JobStore()

    out = asyncio.run(_tool(store, "watch")({"condition": "echo 41 min; exit 1", "instruction": "tell me"}))

    assert out.startswith("watch 1 set, checking every 5 min until ")
    assert "41 min" in out
    [job] = store.list(5)
    assert job["every"] == 300
    assert 86000 < job["expires"] - time.time() <= 86400


def test_no_watch_is_set_when_the_condition_already_holds():
    store = JobStore()

    out = asyncio.run(_tool(store, "watch")({"condition": "echo 27 min; exit 0", "instruction": "tell me"}))

    assert out.startswith("no watch set: the condition is already true")
    assert "27 min" in out
    assert store.list(5) == []


def test_no_watch_is_set_when_the_condition_is_broken():
    store = JobStore()

    out = asyncio.run(_tool(store, "watch")({"condition": "echo no such route >&2; exit 3", "instruction": "tell me"}))

    assert out.startswith("error: no watch set")
    assert "no such route" in out
    assert store.list(5) == []


def test_a_watch_that_would_end_before_it_starts_is_rejected():
    store = JobStore()

    out = asyncio.run(_tool(store, "watch")({"condition": "exit 1", "instruction": "tell me", "until": "2000-01-01T00:00:00"}))

    assert out == "error: until is in the past"


def test_list_jobs_shows_a_watch():
    store = JobStore()
    _watch(store, "exit 1")

    out = asyncio.run(_tool(store, "list_jobs")({}))

    assert out.startswith("1: watch every 5 min until ")
    assert out.endswith("`exit 1` -> tell the owner the bridge is clear")


def test_the_scheduler_pushes_a_due_watch_back_instead_of_deleting_it(monkeypatch):
    store = JobStore()
    job = _watch(store, "exit 1")
    db.Job.update(next_run=time.time() - 1).where(db.Job.id == job["id"]).execute()
    ran = []

    async def execute(job):
        ran.append(job["id"])

    async def stop(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduling.asyncio, "sleep", stop)
    try:
        asyncio.run(scheduling.run_scheduler(store, execute, execute))
    except asyncio.CancelledError:
        pass

    [kept] = store.list(5)
    assert ran == [job["id"]]
    assert kept["next_run"] > time.time() + 290


def test_a_watch_that_comes_true_wakes_the_model_once_and_is_gone(monkeypatch):
    seen = []

    async def run_turn(session, text, store, mcp_tools, transport):
        seen.append(text)
        return "bridge is at 27 min, go now"

    monkeypatch.setattr(app.conversation, "run_turn", run_turn)
    store = JobStore()
    dispatcher = _Dispatcher()
    job = _watch(store, "echo 27 min; exit 0")

    asyncio.run(app.check_watch(job, "base", store, [], dispatcher))

    [text] = seen
    assert "tell the owner the bridge is clear" in text and "27 min" in text
    assert dispatcher.transport.sent == ["bridge is at 27 min, go now"]
    assert store.list(5) == []


def test_a_watch_not_yet_true_stays_quiet_and_keeps_watching():
    store = JobStore()
    dispatcher = _Dispatcher()
    job = _watch(store, "exit 1")

    asyncio.run(app.check_watch(job, "base", store, [], dispatcher))

    assert dispatcher.transport.sent == []
    assert len(store.list(5)) == 1


def test_a_watch_whose_condition_breaks_stops_and_says_why():
    store = JobStore()
    dispatcher = _Dispatcher()
    job = _watch(store, "echo quota exceeded >&2; exit 2")

    asyncio.run(app.check_watch(job, "base", store, [], dispatcher))

    [sent] = dispatcher.transport.sent
    assert sent.startswith(f"watch {job['id']} stopped because its condition failed")
    assert "quota exceeded" in sent
    assert "quota exceeded" in dispatcher.session.notes[0]
    assert store.list(5) == []


def test_a_watch_on_its_last_check_runs_out_and_says_so():
    store = JobStore()
    dispatcher = _Dispatcher()
    job = _watch(store, "exit 1", expires=time.time() + 60)

    asyncio.run(app.check_watch(job, "base", store, [], dispatcher))

    [sent] = dispatcher.transport.sent
    assert sent.startswith(f"watch {job['id']} ran out at ")
    assert sent.endswith("It was set to: tell the owner the bridge is clear")
    assert store.list(5) == []


def test_a_watch_cancelled_while_its_check_ran_stays_quiet():
    store = JobStore()
    dispatcher = _Dispatcher()
    job = _watch(store, "exit 0")
    store.delete(job["id"], 5)

    asyncio.run(app.check_watch(job, "base", store, [], dispatcher))

    assert dispatcher.transport.sent == []
