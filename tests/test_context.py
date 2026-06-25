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
    # Either no compaction, or the retained tail starts on a real user turn.
    assert cut == 0 or _is_user_turn(session.messages[cut])


def test_safe_cut_lands_on_clean_boundary(monkeypatch):
    monkeypatch.setattr(config, "KEEP_RECENT", 2)
    session = Session(1, "base")
    session.messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
    ] * 3
    cut = session._safe_cut()
    assert _is_user_turn(session.messages[cut])


def test_system_includes_base_runtime_summary_pins():
    session = Session(1, "BASEPROMPT")
    session.summary = "EARLIER"
    session.pinned = ["PINNED FACT"]
    rendered = session.system()
    assert "BASEPROMPT" in rendered
    assert "Runtime:" in rendered
    assert "EARLIER" in rendered
    assert "PINNED FACT" in rendered


def test_text_of_joins_only_text_blocks():
    content = [
        {"type": "text", "text": "a"},
        {"type": "tool_use", "id": "x", "name": "n", "input": {}},
        {"type": "text", "text": "b"},
    ]
    assert llm.text_of(content) == "ab"
