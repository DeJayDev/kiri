import asyncio
import types

from kiri import stt
from kiri.transports.discord.client import _voice_attachment


class _Segment:
    def __init__(self, text):
        self.text = text


def test_transcribe_joins_segment_text(monkeypatch):
    model = types.SimpleNamespace(
        transcribe=lambda audio, language=None: ([_Segment(" hello"), _Segment(" world")], None)
    )
    monkeypatch.setattr(stt, "_load_model", lambda: model)
    assert stt._transcribe_sync(b"audio") == "hello world"


def test_transcribe_async_wraps_sync(monkeypatch):
    monkeypatch.setattr(stt, "_transcribe_sync", lambda audio: "transcribed")
    assert asyncio.run(stt.transcribe(b"audio")) == "transcribed"


def test_load_model_without_extra_fails_loud(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", None)
    try:
        stt._load_model()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "stt" in str(exc)


def _message(voice, attachments):
    flags = types.SimpleNamespace(voice=voice)
    return types.SimpleNamespace(flags=flags, attachments=attachments)


def test_voice_attachment_returns_attachment_when_flagged():
    attachment = object()
    assert _voice_attachment(_message(True, [attachment])) is attachment


def test_voice_attachment_none_without_flag():
    assert _voice_attachment(_message(False, [object()])) is None
