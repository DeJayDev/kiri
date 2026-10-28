import asyncio
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from kiri import app, config
from kiri.engine.context import Session
from kiri.scheduling import events
from kiri.scheduling import store as scheduling
from kiri.scheduling.store import JobStore


def test_cron_holds_local_time_across_dst(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "America/Los_Angeles")
    monkeypatch.setattr(scheduling.clock, "now", lambda: datetime(2026, 10, 31, 12, tzinfo=ZoneInfo("America/Los_Angeles")))
    before = scheduling._next_run("0 9 * * *")
    monkeypatch.setattr(scheduling.clock, "now", lambda: datetime(2026, 11, 1, 12, tzinfo=ZoneInfo("America/Los_Angeles")))
    after = scheduling._next_run("0 9 * * *")

    local = ZoneInfo("America/Los_Angeles")
    assert datetime.fromtimestamp(before, local).hour == 9
    assert datetime.fromtimestamp(after, local).hour == 9


def test_event_files_are_claimed_once_and_only_markdown():
    os.makedirs(config.EVENTS_DIR)
    for name, body in [("a.md", "first"), ("b.md", "second"), ("skip.tmp", "no"), (".c.md", "no")]:
        with open(os.path.join(config.EVENTS_DIR, name), "w") as f:
            f.write(body)

    assert events.take() == [("a.md", "first"), ("b.md", "second")]
    assert events.take() == []
    assert sorted(os.listdir(config.EVENTS_DIR)) == [".c.md", "skip.tmp"]


def test_the_scheduler_sleeps_only_until_the_next_job(monkeypatch):
    store = JobStore()
    store.add_once(time.time() + 2, "soon", 1)
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduling.asyncio, "sleep", sleep)

    async def never(*args):
        raise AssertionError("nothing is due")

    try:
        asyncio.run(scheduling.run_scheduler(store, never, never))
    except asyncio.CancelledError:
        pass
    assert 1 < waits[0] <= 2


def test_due_work_runs_and_events_route_to_their_runner(monkeypatch):
    store = JobStore()
    store.add_once(time.time() - 1, "now", 1)
    os.makedirs(config.EVENTS_DIR)
    with open(os.path.join(config.EVENTS_DIR, "ping.md"), "w") as f:
        f.write("deploy finished")
    ran = []

    async def execute(job):
        ran.append(job["instruction"])

    async def execute_event(name, body):
        ran.append((name, body))

    real_sleep = asyncio.sleep
    calls = []

    async def sleep_once(seconds):
        calls.append(seconds)
        if len(calls) > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(scheduling.asyncio, "sleep", sleep_once)
    try:
        asyncio.run(scheduling.run_scheduler(store, execute, execute_event))
    except asyncio.CancelledError:
        pass
    assert ran == ["now", ("ping.md", "deploy finished")]


class _Transport:
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

    def archive(self, channel_id, messages):
        self.archived = messages


def test_a_late_reminder_says_when_it_was_due():
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": None, "instruction": "stretch", "channel_id": 5, "next_run": time.time() - 3600}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    (sent,) = dispatcher.transport.sent
    assert sent.startswith("reminder: stretch\n(late: it was due ")


def test_a_late_job_tells_the_model_it_is_late(monkeypatch):
    seen = []

    async def run_turn(session, text, store, mcp_tools, transport):
        seen.append(text)
        return "ok"

    monkeypatch.setattr(app.conversation, "run_turn", run_turn)
    job = {"id": 1, "cron": "0 9 * * *", "instruction": "brief", "channel_id": 5, "next_run": time.time() - 3600}

    asyncio.run(app.execute_job(job, "base", None, [], _Dispatcher()))

    assert seen[0].startswith("This job was due ")
    assert "running late because you were down" in seen[0]


def test_job_output_is_folded_into_the_next_owner_turn(monkeypatch):
    async def run_turn(session, text, store, mcp_tools, transport):
        return "3 PRs need review"

    monkeypatch.setattr(app.conversation, "run_turn", run_turn)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "0 9 * * *", "instruction": "check PRs", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))
    dispatcher.session.append_user("which ones?")

    content = dispatcher.session.messages[0]["content"]
    assert "check PRs" in content and "3 PRs need review" in content
    assert content.index("3 PRs need review") < content.index("which ones?")
    assert dispatcher.session.notes == []
