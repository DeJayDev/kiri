import asyncio

import pytest

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


def test_the_session_is_checkpointed_before_each_model_call(monkeypatch):
    session = Session(1, "base")
    replies = iter([
        _reply([{"type": "tool_use", "id": "t1", "name": "shell", "input": {}}], "tool_use"),
        _reply([{"type": "text", "text": "done"}], "end_turn"),
    ])

    async def complete(system, messages, schemas):
        return next(replies)

    monkeypatch.setattr(agent.llm, "complete", complete)

    saved = []

    async def persist():
        saved.append(len(session.messages))

    asyncio.run(agent.run(session, "go", _Registry({"shell": lambda: "ok"}), _noop, persist=persist))
    # user turn (1), then user + assistant tool_use + tool_result (3): a growing,
    # always-valid prefix checkpointed before each request.
    assert saved == [1, 3]


def test_a_nudge_mid_tool_loop_rides_in_on_the_tool_result(monkeypatch):
    session = Session(1, "base")
    replies = iter([
        _reply([{"type": "tool_use", "id": "t1", "name": "shell", "input": {}}], "tool_use"),
        _reply([{"type": "text", "text": "done"}], "end_turn"),
    ])

    async def complete(system, messages, schemas):
        return next(replies)

    monkeypatch.setattr(agent.llm, "complete", complete)

    nudged = iter([("also check the weather", None)])

    async def nudges():
        return next(nudged, ("", None))

    result = asyncio.run(agent.run(session, "run it", _Registry({"shell": lambda: "ok"}), _noop, nudges=nudges))
    assert result == "done"
    assert session.messages[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        {"type": "text", "text": "also check the weather"},
    ]


def test_a_nudge_as_the_turn_ends_keeps_it_going(monkeypatch):
    session = Session(1, "base")
    replies = iter([
        _reply([{"type": "text", "text": "here you go"}], "end_turn"),
        _reply([{"type": "text", "text": "and the follow-up"}], "end_turn"),
    ])

    async def complete(system, messages, schemas):
        return next(replies)

    monkeypatch.setattr(agent.llm, "complete", complete)

    nudged = iter([("wait, one more thing", None)])

    async def nudges():
        return next(nudged, ("", None))

    sent = []

    async def notify(message):
        sent.append(message)

    result = asyncio.run(agent.run(session, "hi", _Registry(), notify, nudges=nudges))
    assert sent == ["here you go"]
    assert result == "and the follow-up"
    assert session.messages[2]["content"] == [{"type": "text", "text": "wait, one more thing"}]


def test_a_batch_of_tool_calls_runs_concurrently_and_answers_in_order(monkeypatch):
    session = Session(1, "base")
    both_started = asyncio.Event()
    started = []
    replies = iter([
        _reply(
            [
                {"type": "tool_use", "id": "a", "name": "slow", "input": {}},
                {"type": "tool_use", "id": "b", "name": "fast", "input": {}},
            ],
            "tool_use",
        ),
        _reply([{"type": "text", "text": "done"}], "end_turn"),
    ])

    class _Concurrent:
        def schemas(self):
            return []

        async def run(self, name, args):
            started.append(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 1)
            return f"{name} ok"

    async def complete(system, messages, schemas):
        return next(replies)

    monkeypatch.setattr(agent.llm, "complete", complete)

    assert asyncio.run(agent.run(session, "go", _Concurrent(), _noop)) == "done"
    results = session.messages[2]["content"]
    assert [(r["tool_use_id"], r["content"]) for r in results] == [("a", "slow ok"), ("b", "fast ok")]


def test_reload_in_a_batch_still_answers_every_call(monkeypatch):
    session = Session(1, "base")

    async def complete(system, messages, schemas):
        return _reply(
            [
                {"type": "tool_use", "id": "t1", "name": "shell", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "reload", "input": {}},
            ],
            "tool_use",
        )

    def boom():
        raise Restart()

    monkeypatch.setattr(agent.llm, "complete", complete)

    try:
        asyncio.run(agent.run(session, "go", _Registry({"shell": lambda: "ok", "reload": boom}), _noop))
    except Restart:
        pass
    results = session.messages[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]


def test_a_reply_cut_off_at_the_output_limit_fails_loud(monkeypatch):
    session = Session(1, "base")

    async def complete(system, messages, schemas):
        return _reply([{"type": "text", "text": "Here are the first half of"}], "max_tokens")

    monkeypatch.setattr(agent.llm, "complete", complete)

    with pytest.raises(RuntimeError, match="output limit"):
        asyncio.run(agent.run(session, "write it all", _Registry(), _noop))
    assert session.messages[-1]["role"] == "user"


def test_a_refusal_fails_loud_with_its_details(monkeypatch):
    session = Session(1, "base")

    async def complete(system, messages, schemas):
        return {**_reply([], "refusal"), "stop_details": {"type": "refusal", "category": "cyber"}}

    monkeypatch.setattr(agent.llm, "complete", complete)

    with pytest.raises(RuntimeError, match="refused to answer: .*cyber"):
        asyncio.run(agent.run(session, "hi", _Registry(), _noop))


def test_tool_calls_are_on_the_session_only_while_they_run(monkeypatch):
    session = Session(1, "base")
    seen = []
    replies = iter([
        _reply([{"type": "tool_use", "id": "a", "name": "shell", "input": {"command": "ls"}}], "tool_use"),
        _reply([{"type": "text", "text": "done"}], "end_turn"),
    ])

    async def complete(system, messages, schemas):
        return next(replies)

    def shell():
        seen.append([call["name"] for call in session.running])
        return "ok"

    monkeypatch.setattr(agent.llm, "complete", complete)

    asyncio.run(agent.run(session, "go", _Registry({"shell": shell}), _noop))
    assert seen == [["shell"]]
    assert session.running == []
