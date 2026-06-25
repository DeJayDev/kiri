import asyncio

from kiri import app


class _Bot:
    def __init__(self):
        self.delivered = []

    async def deliver(self, channel_id, reply):
        self.delivered.append((channel_id, reply))


def test_one_shot_reminder_delivers_text_without_agent(monkeypatch):
    async def fail_run_turn(*args, **kwargs):
        raise AssertionError("one-shot reminders should not run through the agent")

    monkeypatch.setattr(app.conversation, "run_turn", fail_run_turn)
    bot = _Bot()
    job = {"id": 1, "cron": None, "instruction": "stretch", "channel_id": 5}

    asyncio.run(app.execute_job(job, "base", store=None, mcp_tools=[], bot=bot))

    assert bot.delivered == [(5, "Reminder: stretch")]


def test_recurring_job_runs_through_agent(monkeypatch):
    calls = []

    async def fake_run_turn(session, text, store, mcp_tools, on_usage=None):
        calls.append((session.channel_id, text, store, mcp_tools, on_usage))
        return "done"

    monkeypatch.setattr(app.conversation, "run_turn", fake_run_turn)
    bot = _Bot()
    store = object()
    mcp_tools = []
    job = {"id": 1, "cron": "* * * * *", "instruction": "tick", "channel_id": 5}

    asyncio.run(app.execute_job(job, "base", store, mcp_tools, bot, on_usage="usage"))

    assert bot.delivered == [(5, "done")]
    assert calls == [(5, "tick", store, mcp_tools, "usage")]
