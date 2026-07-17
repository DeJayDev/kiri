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


def test_reload_midloop_leaves_a_valid_completed_tool_result(monkeypatch):
    session = Session(1, "base")

    async def complete(system, messages, schemas):
        return _reply([{"type": "tool_use", "id": "t1", "name": "reload", "input": {}}], "tool_use")

    def boom():
        raise Restart()

    monkeypatch.setattr(agent.llm, "complete", complete)

    raised = False
    try:
        asyncio.run(agent.run(session, "reload yourself", _Registry({"reload": boom})))
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

    result = asyncio.run(agent.run(session, None, _Registry()))
    assert result == "all done"
    assert session.messages[0]["content"] == "do it"
