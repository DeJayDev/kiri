import asyncio
import os

from kiri import config
from kiri.tools import send_file
from kiri.transports.discorddm import _files, _split


def test_a_short_reply_is_one_message():
    assert _split("hi") == ["hi"]


def test_a_long_reply_splits_on_paragraphs_under_the_limit():
    paragraphs = ["p" * 900 for _ in range(5)]
    chunks = _split("\n\n".join(paragraphs))
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "\n\n".join(chunks) == "\n\n".join(paragraphs)


def test_a_code_block_cut_in_half_closes_and_reopens_its_fence():
    code = "```python\n" + "\n".join(f"line_{i} = '{'x' * 40}'" for i in range(80)) + "\n```"
    chunks = _split(code)
    assert len(chunks) > 1
    assert all(chunk.count("```") == 2 for chunk in chunks)
    assert all(chunk.startswith("```python") for chunk in chunks)


def test_a_line_longer_than_a_message_is_hard_cut():
    chunks = _split("a" * 4500)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks) == "a" * 4500


class _Attachment:
    def __init__(self, filename, content_type, body=b"data"):
        self.filename = filename
        self.content_type = content_type
        self.body = body

    async def save(self, path):
        with open(path, "wb") as f:
            f.write(self.body)


class _Message:
    def __init__(self, attachments):
        self.id = 77
        self.attachments = attachments


def test_non_image_attachments_are_saved_to_the_inbox():
    voice = _Attachment("voice.ogg", "audio/ogg")
    message = _Message([_Attachment("../report.pdf", "application/pdf"), _Attachment("a.png", "image/png"), voice])

    paths = asyncio.run(_files(message, voice))

    assert paths == [os.path.join(config.INBOX_DIR, "77", "report.pdf")]
    with open(paths[0], "rb") as f:
        assert f.read() == b"data"


class _Transport:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    async def send_file(self, channel_id, path):
        self.sent.append(path)
        return self.error


def test_send_file_reports_a_missing_path_without_sending(tmp_path):
    transport = _Transport()
    out = asyncio.run(send_file.build(transport, 1)({"path": str(tmp_path / "nope.png")}))
    assert out.startswith("error: no file at")
    assert transport.sent == []


def test_send_file_passes_an_upload_error_back(tmp_path):
    path = tmp_path / "big.mp4"
    path.write_bytes(b"x")
    out = asyncio.run(send_file.build(_Transport("error: discord 413: too large"), 1)({"path": str(path)}))
    assert out == "error: discord 413: too large"
