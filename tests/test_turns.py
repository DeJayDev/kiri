import asyncio
from contextlib import asynccontextmanager

import pytest

from kiri import turns
from kiri.engine.providers.base import AuthRequired
from kiri.tools.reload import Restart
from kiri.transports.base import Inbound


class _Transport:
    name = "fake"

    def __init__(self):
        self.sent = []

    async def send(self, channel_id, text):
        self.sent.append(text)

    @asynccontextmanager
    async def typing(self, channel_id):
        yield


class _Sessions:
    def __init__(self):
        self.saved = []
        self.dropped = []

    def get(self, channel_id):
        return f"session-{channel_id}"

    def save(self, session):
        self.saved.append(session)

    def drop(self, channel_id):
        self.dropped.append(channel_id)


@pytest.fixture
def rig(monkeypatch):
    transport = _Transport()
    sessions = _Sessions()
    dispatcher = turns.Dispatcher(transport, sessions, store=None, mcp_tools=[])
    return dispatcher, transport, sessions


def _msg(text):
    return Inbound(channel_id=1, text=text)


def test_a_slow_turn_says_it_is_still_alive(rig, monkeypatch):
    # The owner cannot see the agent loop. A long turn that says nothing is
    # indistinguishable from a hung one.
    dispatcher, transport, _ = rig
    slept = []

    async def instant(delay):
        slept.append(delay)
        if len(slept) > 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", instant)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dispatcher._slow_note(1))

    assert slept[:2] == [60, 300]
    assert transport.sent == ["still working (1m).", "still working (6m)."]


def test_a_turn_runs_and_the_session_is_saved(rig, monkeypatch):
    dispatcher, transport, sessions = rig
    monkeypatch.setattr(dispatcher, "_turn", lambda s, text: _reply(f"echo: {text}"))

    asyncio.run(_run(dispatcher, "hello"))
    assert transport.sent == ["echo: hello"]
    assert sessions.saved == ["session-1"]


def test_two_messages_in_one_loop_batch_are_answered_in_order(rig, monkeypatch):
    dispatcher, transport, _ = rig

    async def turn(session, text):
        return f"reply to {text}"

    monkeypatch.setattr(dispatcher, "_turn", turn)

    async def go():
        first = await dispatcher.on_message(_msg("FIRST"))
        # no await between the two sends: same gateway batch
        await dispatcher.on_message(_msg("SECOND"))
        await first

    asyncio.run(go())
    assert transport.sent == ["reply to FIRST", "reply to SECOND"]


def test_a_message_mid_turn_queues_as_a_follow_up(rig, monkeypatch):
    dispatcher, transport, _ = rig
    started, release = asyncio.Event(), asyncio.Event()

    async def turn(session, text):
        if text == "first":
            started.set()
            await release.wait()
        return f"done: {text}"

    monkeypatch.setattr(dispatcher, "_turn", turn)

    async def go():
        task = await dispatcher.on_message(_msg("first"))
        await started.wait()
        assert await dispatcher.on_message(_msg("second")) is None
        release.set()
        await task

    asyncio.run(go())
    assert transport.sent == ["done: first", "done: second"]


def test_stop_clears_the_queue_and_cancels_the_running_turn(rig, monkeypatch):
    dispatcher, transport, sessions = rig
    started = asyncio.Event()

    async def turn(session, text):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(dispatcher, "_turn", turn)

    async def go():
        task = await dispatcher.on_message(_msg("long one"))
        await started.wait()
        await dispatcher.on_message(_msg("queued"))
        await dispatcher.on_message(_msg("stop"))
        await task

    asyncio.run(go())
    assert transport.sent == ["stopped."]
    assert sessions.dropped == [1]
    assert sessions.saved == []


def test_stop_with_nothing_running_says_so(rig):
    asyncio.run(_stop(rig[0]))
    assert rig[1].sent == ["nothing running."]


def test_shutdown_cancellation_is_not_swallowed(rig, monkeypatch):
    dispatcher, _, sessions = rig
    started = asyncio.Event()

    async def turn(session, text):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(dispatcher, "_turn", turn)

    async def go():
        task = await dispatcher.on_message(_msg("long one"))
        await started.wait()
        # shutdown-style cancel, not the owner's `stop`
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert sessions.dropped == [1]
    assert sessions.saved == []


def test_an_error_rolls_the_session_back(rig, monkeypatch):
    dispatcher, transport, sessions = rig

    async def boom(session, text):
        raise RuntimeError("exa exploded")

    monkeypatch.setattr(dispatcher, "_turn", boom)

    asyncio.run(_run(dispatcher, "search"))
    assert transport.sent == ["error: exa exploded"]
    assert sessions.dropped == [1]
    assert sessions.saved == []


def test_expired_auth_logs_in_then_replays_the_same_turn(rig, monkeypatch):
    dispatcher, transport, sessions = rig

    class _Provider:
        name = "xai"

    attempts = []

    async def turn(session, text):
        attempts.append(text)
        if len(attempts) == 1:
            raise AuthRequired(_Provider(), "expired")
        return f"done: {text}"

    async def reauth(channel, provider):
        await transport.send(channel, f"{provider.name} login needed")

    monkeypatch.setattr(dispatcher, "_turn", turn)
    monkeypatch.setattr(dispatcher, "reauth", reauth)

    asyncio.run(_run(dispatcher, "what's on my calendar"))
    assert attempts == ["what's on my calendar", "what's on my calendar"]
    assert transport.sent == ["xai login needed", "done: what's on my calendar"]
    assert sessions.dropped == [1]
    assert sessions.saved == ["session-1"]


def test_reload_saves_the_turn_and_marks_a_resume(rig, monkeypatch):
    dispatcher, transport, sessions = rig
    restarted, marks = [], []

    async def turn(session, text):
        raise Restart()

    monkeypatch.setattr(dispatcher, "_turn", turn)
    monkeypatch.setattr(turns.reload, "restart", lambda: restarted.append(True))
    monkeypatch.setattr(turns.resume, "mark", marks.append)

    asyncio.run(_run(dispatcher, "reload yourself"))
    assert transport.sent == ["reloading."]
    assert sessions.saved == ["session-1"]
    assert sessions.dropped == []
    assert marks == [1]
    assert restarted == [True]


async def _reply(text):
    return text


async def _run(dispatcher, text):
    await (await dispatcher.on_message(_msg(text)))


async def _stop(dispatcher):
    await dispatcher.on_message(_msg("stop"))
