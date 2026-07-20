import asyncio

from kiri import config
from kiri.engine import llm
from kiri.engine.context import Session, _is_user_turn


def _pair():
    return [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "shell", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": [{"type": "text", "text": "yep"}]},
    ]


def test_safe_cut_never_orphans_tool_result(monkeypatch):
    monkeypatch.setattr(config, "KEEP_RECENT", 3)
    session = Session(1, "base")
    session.messages = _pair()
    cut = session._safe_cut()
    assert cut == 0 or _is_user_turn(session.messages[cut])


def test_seal_fills_a_tool_use_left_dangling_by_a_restart():
    session = Session(1, "base")
    session.messages = [
        {"role": "user", "content": "run it"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "shell", "input": {}}]},
    ]
    session.seal_dangling_tools()
    assert session.messages[-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "a", "content": "interrupted by a restart"}
    ]


def test_seal_is_a_noop_when_the_last_turn_is_already_clean():
    session = Session(1, "base")
    session.messages = [{"role": "assistant", "content": [{"type": "text", "text": "done"}]}]
    session.seal_dangling_tools()
    assert len(session.messages) == 1


def test_the_date_lives_in_the_turn_not_the_system_prompt():
    session = Session(1, "BASEPROMPT")
    session.append_user("hi")
    assert "Today is" in session.messages[0]["content"]
    assert not any("Today is" in part for part in session.system())


def test_compaction_reports_its_tokens_to_the_usage_sink(monkeypatch):
    monkeypatch.setattr(config, "KEEP_RECENT", 2)
    monkeypatch.setattr(config, "COMPACT_AT", 0.5)
    monkeypatch.setattr(config, "MODEL_CONTEXT", 100)

    class _Provider:
        async def complete(self, system, messages, tools, model=None):
            return {
                "content": [{"type": "text", "text": "BRIEF"}],
                "usage": {"input_tokens": 900, "output_tokens": 30},
            }

    seen = []
    llm.use(_Provider(), sink=seen.append)

    session = Session(1, "base")
    session.messages = _pair()
    session.last_input_tokens = 90
    asyncio.run(session.maybe_compact())

    assert session.summary == "BRIEF"
    assert seen == [{"input_tokens": 900, "output_tokens": 30}]
    # The summarizer's own input size must not become the session's, or it would
    # re-trigger compaction on the next turn.
    assert session.last_input_tokens == 90


def test_context_size_counts_cached_tokens(monkeypatch):
    session = Session(1, "base")
    session.record_usage(
        {"input_tokens": 200, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 150000}
    )
    assert session.last_input_tokens == 151200
