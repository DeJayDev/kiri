import types

from kiri import stt


class _Segment:
    def __init__(self, text):
        self.text = text


def test_transcribe_joins_segment_text(monkeypatch):
    model = types.SimpleNamespace(
        transcribe=lambda audio, language=None: ([_Segment(" hello"), _Segment(" world")], None)
    )
    monkeypatch.setattr(stt, "_load_model", lambda: model)
    assert stt._transcribe_sync(b"audio") == "hello world"


def test_load_model_without_extra_fails_loud(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", None)
    try:
        stt._load_model()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "stt" in str(exc)
