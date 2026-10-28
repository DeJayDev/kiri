import asyncio
import os

from kiri import config
from kiri.scheduling import events
from kiri.tools import task
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


def test_a_waited_task_answers_from_a_fresh_session(monkeypatch):
    seen = []

    async def complete(system, messages, schemas, on_text=None):
        seen.append(list(messages))
        return _reply([{"type": "text", "text": "42"}], "end_turn")

    monkeypatch.setattr(task.agent.llm, "complete", complete)
    run = task.build(1, "base", _Registry)

    assert asyncio.run(run({"prompt": "what is six times seven", "wait": True})) == "42"
    assert len(seen[0]) == 1
    assert seen[0][0]["content"].startswith("what is six times seven")


def test_a_reload_inside_a_task_comes_back_as_an_error(monkeypatch):
    async def complete(system, messages, schemas, on_text=None):
        return _reply([{"type": "tool_use", "id": "r", "name": "reload", "input": {}}], "tool_use")

    def restart():
        raise Restart()

    monkeypatch.setattr(task.agent.llm, "complete", complete)
    run = task.build(1, "base", lambda: _Registry({"reload": restart}))

    assert asyncio.run(run({"prompt": "reload", "wait": True})).startswith("error: reload is not available")


def test_a_background_task_becomes_an_event():
    os.makedirs(config.EVENTS_DIR)
    out = asyncio.run(task.build(1, "base", _Registry)({"prompt": "check the build", "wait": False}))

    assert out.startswith("started in the background")
    [(name, body)] = events.take()
    assert name.startswith("task-") and body == "check the build"
