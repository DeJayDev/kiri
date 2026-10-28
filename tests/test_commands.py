import asyncio
from contextlib import asynccontextmanager

from kiri import resume, turns
from kiri.engine.sessions import SessionStore
from kiri.tools import ask
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


def _dispatcher():
    transport = _Transport()
    sessions = SessionStore("base")
    return turns.Dispatcher(transport, sessions, store=None, mcp_tools=[]), transport, sessions


def _say(dispatcher, text):
    async def go():
        task = await dispatcher.on_message(Inbound(channel_id=1, text=text))
        if task:
            await task

    asyncio.run(go())


def test_new_starts_a_fresh_session_that_survives_a_reload():
    dispatcher, transport, sessions = _dispatcher()
    session = sessions.get(1)
    session.messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "reply"}]
    session.summary = "old summary"
    sessions.save(session)

    _say(dispatcher, "/new")

    assert transport.sent == ["fresh session."]
    reloaded = SessionStore("base").get(1)
    assert (reloaded.messages, reloaded.summary) == ([], "")


def test_retry_resumes_an_unanswered_checkpoint_without_new_text(monkeypatch):
    dispatcher, transport, sessions = _dispatcher()
    session = sessions.get(1)
    session.messages = [{"role": "user", "content": "do the thing"}]
    sessions.save(session)
    calls = []

    async def turn(session, text, images=None):
        calls.append(text)
        return "done"

    monkeypatch.setattr(dispatcher, "_turn", turn)
    _say(dispatcher, "/retry")

    assert calls == [None]
    assert transport.sent == ["done"]


def test_retry_with_nothing_unanswered_says_so(monkeypatch):
    dispatcher, transport, sessions = _dispatcher()
    session = sessions.get(1)
    session.messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    async def turn(session, text, images=None):
        raise AssertionError("nothing should run")

    monkeypatch.setattr(dispatcher, "_turn", turn)
    _say(dispatcher, "/retry")

    assert transport.sent == ["nothing to retry."]


def test_a_finished_turn_leaves_no_inflight_marker(monkeypatch):
    dispatcher, _, _ = _dispatcher()

    async def turn(session, text, images=None):
        return "ok"

    monkeypatch.setattr(dispatcher, "_turn", turn)
    _say(dispatcher, "hi")

    assert resume.take_inflight() is None


def test_a_turn_killed_mid_flight_leaves_its_channel_marked():
    resume.begin(9)
    assert resume.take_inflight() == 9
    assert resume.take_inflight() is None


def test_the_heartbeat_names_a_pending_question_instead_of_working(monkeypatch):
    dispatcher, transport, _ = _dispatcher()
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(turns.asyncio, "sleep", sleep)
    monkeypatch.setitem(ask.waiting, 1, "ship it?")

    try:
        asyncio.run(dispatcher._slow_note(1))
    except asyncio.CancelledError:
        pass

    assert transport.sent == ["waiting on your answer: ship it?"]

