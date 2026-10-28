import asyncio

from kiri.engine.sessions import SessionStore
from kiri.tools import history


def test_compacted_messages_are_archived_on_save_and_readable_by_history():
    store = SessionStore("base")
    session = store.get(3)
    session.archived = [
        {"role": "user", "content": "find flights"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "web_search", "input": {"query": "SFO-NRT"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ANA $900"}]},
    ]
    store.save(session)

    out = asyncio.run(history.build(3)({}))
    assert out.splitlines() == [
        "user: find flights",
        "assistant -> tool web_search({'query': 'SFO-NRT'})",
        "tool_result: ANA $900",
    ]
    assert session.archived == []


def test_history_pages_back_from_the_newest():
    store = SessionStore("base")
    store.archive(3, [{"role": "user", "content": f"m{i}"} for i in range(5)])

    out = asyncio.run(history.build(3)({"count": 2, "skip": 1}))
    assert out.splitlines() == ["user: m2", "user: m3"]


def test_new_archives_the_conversation_it_clears():
    store = SessionStore("base")
    session = store.get(3)
    session.messages = [{"role": "user", "content": "old thread"}]
    store.save(session)

    store.reset(3)

    assert asyncio.run(history.build(3)({})) == "user: old thread"


def test_another_channels_history_stays_out():
    SessionStore("base").archive(4, [{"role": "user", "content": "elsewhere"}])
    assert asyncio.run(history.build(3)({})) == "no earlier messages"
