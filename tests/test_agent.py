import asyncio

from kiri.engine import agent
from kiri.engine.context import Session
from kiri.tools.reload import Restart


class _Registry:
    def __init__(self, outputs=None):
        self.outputs = outputs or {}

    def schemas(self):
        return []

    async def run(self, name, args):
        return self.outputs[name]()


def _reply(blocks, stop_reason):
    return {"content": blocks, "stop_reason": stop_reason, "usage": {}}


async def _noop(_message):
    pass


def test_reload_midloop_leaves_a_valid_completed_tool_result(monkeypatch):
    session = Session(1, "base")

    async def complete(system, messages, schemas):
        return _reply([{"type": "tool_use", "id": "t1", "name": "reload", "input": {}}], "tool_use")

    def boom():
        raise Restart()

    monkeypatch.setattr(agent.llm, "complete", complete)

    raised = False
    try:
        asyncio.run(agent.run(session, "reload yourself", _Registry({"reload": boom}), _noop))
    except Restart:
        raised = True

    assert raised
    assert session.messages[-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": "reloaded successfully - welcome back",
            }
        ],
    }


def test_resume_continues_without_injecting_a_user_turn(monkeypatch):
    session = Session(1, "base")
    session.messages = [
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "reload", "input": {}}]},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "reloaded successfully - welcome back"}],
        },
    ]

    async def complete(system, messages, schemas):
        return _reply([{"type": "text", "text": "all done"}], "end_turn")

    monkeypatch.setattr(agent.llm, "complete", complete)
    monkeypatch.setattr(agent.llm, "text_of", lambda content: content[0]["text"])

    result = asyncio.run(agent.run(session, None, _Registry(), _noop))
    assert result == "all done"
    assert session.messages[0]["content"] == "do it"


def test_text_alongside_a_tool_call_is_delivered_not_just_the_final_reply(monkeypatch):
    session = Session(1, "base")
    replies = iter([
        _reply(
            [{"type": "text", "text": "on it"}, {"type": "tool_use", "id": "t1", "name": "shell", "input": {}}],
            "tool_use",
        ),
        _reply([{"type": "text", "text": "done"}], "end_turn"),
    ])

    async def complete(system, messages, schemas):
        return next(replies)

    monkeypatch.setattr(agent.llm, "complete", complete)

    sent = []

    async def notify(message):
        sent.append(message)

    result = asyncio.run(agent.run(session, "go", _Registry({"shell": lambda: "ok"}), notify))
    assert sent == ["on it"]
    assert result == "done"
