from kiri.engine.sessions import SessionStore


def test_session_persists_across_stores():
    store = SessionStore("BASE")
    session = store.get(42)
    session.messages = [{"role": "user", "content": "hi"}]
    session.summary = "earlier"
    session.last_input_tokens = 99
    store.save(session)

    reopened = SessionStore("BASE")
    loaded = reopened.get(42)
    assert loaded.messages == [{"role": "user", "content": "hi"}]
    assert loaded.summary == "earlier"
    assert loaded.last_input_tokens == 99


def test_drop_discards_a_turn_left_dangling_by_an_error():
    store = SessionStore("BASE")
    session = store.get(5)
    session.messages = [{"role": "user", "content": "hi"}]
    store.save(session)

    session.messages.append({"role": "user", "content": "search the web"})
    session.messages.append(
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "web_search", "input": {}}]}
    )

    store.drop(5)
    assert store.get(5).messages == [{"role": "user", "content": "hi"}]


def test_a_dropped_turn_keeps_the_notes_waiting_for_the_owner():
    store = SessionStore("base")
    store.get(1).note("job output")
    store.drop(1)
    assert store.get(1).notes == ["job output"]
