import asyncio
import time

from kiri import app
from kiri.engine.context import Session
from kiri.engine.providers.base import AuthRequired
from kiri.tools.reload import Restart


class _Transport:
    name = "fake"

    def __init__(self):
        self.sent = []

    async def send(self, channel_id, text):
        self.sent.append((channel_id, text))


class _Sessions:
    def __init__(self):
        self.session = Session(5, "base")

    def get(self, channel_id):
        return self.session

    def archive(self, channel_id, messages):
        pass


class _Dispatcher:
    def __init__(self):
        self.transport = _Transport()
        self.sessions = _Sessions()
        self.reauths = []

    async def reauth(self, channel_id, provider):
        self.reauths.append((channel_id, provider.name))


def test_one_shot_reminder_delivers_text_without_agent(monkeypatch):
    async def fail_run_turn(*args, **kwargs):
        raise AssertionError("one-shot reminders should not run through the agent")

    monkeypatch.setattr(app.conversation, "run_turn", fail_run_turn)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": None, "instruction": "stretch", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", store=None, mcp_tools=[], dispatcher=dispatcher))

    assert dispatcher.transport.sent == [(5, "reminder: stretch")]


def test_recurring_job_runs_through_agent(monkeypatch):
    calls = []

    async def fake_run_turn(session, text, store, mcp_tools, transport):
        calls.append((session.channel_id, text, store, mcp_tools))
        return "done"

    monkeypatch.setattr(app.conversation, "run_turn", fake_run_turn)
    dispatcher = _Dispatcher()
    store = object()
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", store, [], dispatcher))

    assert dispatcher.transport.sent == [(5, "done")]
    channel, text, passed_store, passed_tools = calls[0]
    assert (channel, passed_store, passed_tools) == (5, store, [])
    assert text == f"tick\n\n{app._JOB_REPORT}"


def test_job_hitting_expired_auth_reauths_then_replays(monkeypatch):
    class _Provider:
        name = "xai"

    attempts = []

    async def flaky_run_turn(session, text, store, mcp_tools, transport):
        attempts.append(text)
        if len(attempts) == 1:
            raise AuthRequired(_Provider(), "expired")
        return "done after login"

    monkeypatch.setattr(app.conversation, "run_turn", flaky_run_turn)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    assert dispatcher.reauths == [(5, "xai")]
    replayed = f"tick\n\n{app._JOB_REPORT}"
    assert attempts == [replayed, replayed]
    assert dispatcher.transport.sent == [(5, "done after login")]


def test_job_error_is_reported_not_raised(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(app.conversation, "run_turn", boom)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    assert dispatcher.transport.sent == [(5, "job error: tool exploded")]


def test_reload_in_a_scheduled_job_says_so_instead_of_an_empty_error(monkeypatch):
    async def wants_reload(session, text, store, mcp_tools, transport):
        raise Restart()

    monkeypatch.setattr(app.conversation, "run_turn", wants_reload)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    (_channel, reply), = dispatcher.transport.sent
    assert "reload not available from a job" in reply


def test_a_detached_run_takes_its_instruction_verbatim_and_notes_the_delivery(monkeypatch):
    calls = []

    async def fake_run_turn(session, text, store, mcp_tools, transport):
        calls.append(text)
        return "background task ok"

    monkeypatch.setattr(app.conversation, "run_turn", fake_run_turn)
    dispatcher = _Dispatcher()

    asyncio.run(app.run_detached(5, "say exactly: background task ok", "base", None, [], dispatcher))

    assert calls == ["say exactly: background task ok"]
    assert dispatcher.transport.sent == [(5, "background task ok")]
    [note] = dispatcher.sessions.session.notes
    assert "do not reply to it or send it again" in note
    assert note.endswith("\n\nbackground task ok")
    assert "say exactly" not in note


def test_a_failed_detached_run_notes_the_error_without_calling_it_a_record(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(app.conversation, "run_turn", boom)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "* * * * *", "instruction": "check PRs", "channel_id": 5, "next_run": time.time()}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    [note] = dispatcher.sessions.session.notes
    assert "failed" in note and "job error: tool exploded" in note and "check PRs" in note
    assert "do not reply" not in note
