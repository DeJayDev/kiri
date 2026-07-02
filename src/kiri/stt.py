import asyncio
import io

from kiri import config

# On-device speech-to-text via faster-whisper (CTranslate2). The model is a
# heavy optional dependency, so it's lazy-loaded the first time a voice message
# arrives and kept as a process-wide singleton afterward.

_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from faster_whisper import WhisperModel  # pyright: ignore[reportMissingImports]
    except ImportError:
        raise RuntimeError(
            "voice messages need the STT extra. install it with "
            "`uv sync --extra stt` (or `pip install kiri[stt]`)"
        )
    _model = WhisperModel(
        config.STT_MODEL,
        device=config.STT_DEVICE,
        compute_type=config.STT_COMPUTE_TYPE,
    )
    return _model


def _transcribe_sync(audio):
    model = _load_model()
    # faster-whisper decodes the OGG/Opus container itself via bundled PyAV.
    segments, _info = model.transcribe(io.BytesIO(audio), language=config.STT_LANGUAGE)
    return "".join(segment.text for segment in segments).strip()


async def transcribe(audio):
    # Transcription is CPU-bound and blocking; keep it off the event loop.
    return await asyncio.to_thread(_transcribe_sync, audio)
