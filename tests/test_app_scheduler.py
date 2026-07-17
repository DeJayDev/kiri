import asyncio

from kiri import app
from kiri.engine.providers.base import AuthRequired
from kiri.tools.reload import Restart


class _Transport:
    name = "fake"

    def __init__(self):
        self.sent = []

    async def send(self, channel_id, text):
        self.sent.append((channel_id, text))


class _Dispatcher:
    def __init__(self):
        self.transport = _Transport()
        self.reauths = []

    async def reauth(self, channel_id, provider):
        self.reauths.append((channel_id, provider.name))


def test_one_shot_reminder_delivers_text_without_agent(monkeypatch):
    async def fail_run_turn(*args, **kwargs):
        raise AssertionError("one-shot reminders should not run through the agent")

    monkeypatch.setattr(app.conversation, "run_turn", fail_run_turn)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": None, "instruction": "stretch", "channel_id": 5}

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
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5}

    asyncio.run(app.execute_job(job, "base", store, [], dispatcher))

    assert dispatcher.transport.sent == [(5, "done")]
    assert calls == [(5, "tick", store, [])]


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
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    assert dispatcher.reauths == [(5, "xai")]
    assert attempts == ["tick", "tick"]
    assert dispatcher.transport.sent == [(5, "done after login")]


def test_job_error_is_reported_not_raised(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(app.conversation, "run_turn", boom)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    assert dispatcher.transport.sent == [(5, "job error: tool exploded")]


def test_reload_in_a_scheduled_job_says_so_instead_of_an_empty_error(monkeypatch):
    async def wants_reload(session, text, store, mcp_tools, transport):
        raise Restart()

    monkeypatch.setattr(app.conversation, "run_turn", wants_reload)
    dispatcher = _Dispatcher()
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5}

    asyncio.run(app.execute_job(job, "base", None, [], dispatcher))

    (_channel, reply), = dispatcher.transport.sent
    assert "reload not available from a job" in reply
