from kiri.engine.sessions import SessionStore


def test_session_persists_across_stores():
    store = SessionStore("BASE")
    session = store.get(42)
    session.messages = [{"role": "user", "content": "hi"}]
    session.summary = "earlier"
    session.pinned = ["a fact"]
    session.last_input_tokens = 99
    store.save(session)

    reopened = SessionStore("BASE")
    loaded = reopened.get(42)
    assert loaded.messages == [{"role": "user", "content": "hi"}]
    assert loaded.summary == "earlier"
    assert loaded.pinned == ["a fact"]
    assert loaded.last_input_tokens == 99


def test_get_caches_same_instance():
    store = SessionStore("BASE")
    assert store.get(1) is store.get(1)


def test_unknown_channel_starts_fresh():
    store = SessionStore("BASE")
    session = store.get(7)
    assert session.messages == []
    assert session.base_system == "BASE"
